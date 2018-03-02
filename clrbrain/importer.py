#!/bin/bash
# Image stack importer
# Author: David Young, 2017, 2018
"""Imports image stacks using Bioformats.

Bioformats is access through Python-Bioformats and Javabridge.
Images will be imported into a 4/5D Numpy array.

Attributes:
    PIXEL_DTYPE: Dictionary of corresponding data types for 
        output given by Bioformats library. Alternatively, should detect
        pixel data type directly using parse_ome_raw().
    IMAGE5D_NP_VER: image5d Numpy saved array version number, which should
        be incremented with any change to the image5d or its support "info"
        save array format.
    SUFFIX_IMAGE5D: Suffix for the image5d Numpy array archive.
    SUFFIX_INFO: Suffix for the image5d Numpy array "info" support archive.
"""

import os
from time import time
import glob
import multiprocessing as mp
from xml import etree as et

import numpy as np
import javabridge as jb
import bioformats as bf
from skimage import io
from skimage import transform

from clrbrain import chunking
from clrbrain import detector
from clrbrain import plot_2d
from clrbrain import plot_3d
from clrbrain import lib_clrbrain

# pixel type enumeration based on:
# http://downloads.openmicroscopy.org/bio-formats-cpp/5.1.8/api/classome_1_1xml_1_1model_1_1enums_1_1PixelType.html
# http://downloads.openmicroscopy.org/bio-formats-cpp/5.1.8/api/PixelType_8h_source.html
PIXEL_DTYPE = {
    0: np.int8,
    1: np.uint8,
    2: np.int16,
    3: np.uint16,
    4: np.int32,
    5: np.uint32,
    6: np.float32,
    7: np.double
}

# image5d info archive versions:
# 10: started at 10 because of previous versions prior to numbering; 
#     fixed saved resolutions to contain only the given series
# 11: sizes uses the image5d shape rather than the original image's size
# 12: fixed replacing dtype, near_min/max when saving image in transpose_npy
# 13: change near_min/max to array with element for each channel; add 
#     "scaling" and "plane" fields for transposed images
IMAGE5D_NP_VER = 13 # image5d Numpy saved array version number
SUFFIX_IMAGE5D = "_image5d.npz" # should actually be .npy
SUFFIX_INFO = "_info.npz"

CHANNEL_SEPARATOR = "_ch_"

def start_jvm(heap_size="8G"):
    """Starts the JVM for Python-Bioformats.
    
    Args:
        heap_size: JVM heap size, defaulting to 8G.
    """
    jb.start_vm(class_path=bf.JARS, max_heap_size=heap_size)

def parse_ome(filename):
    """Parses metadata for image name and size information using Bioformats'
    OME XML wrapper.
    
    Args:
        filename: Image file, assumed to have metadata in OME XML format.
    
    Returns:
        names: array of names of seriess within the file.
        sizes: array of tuples with dimensions for each series. Dimensions
            will be given as (time, z, y, x, channels).
    """
    time_start = time()
    metadata = bf.get_omexml_metadata(filename)
    ome = bf.OMEXML(metadata)
    count = ome.image_count
    names, sizes = [], []
    for i in range(count):
        image = ome.image(i)
        names.append(image.Name)
        pixel = image.Pixels
        size = (pixel.SizeT, pixel.SizeZ, pixel.SizeY, pixel.SizeX, pixel.SizeC)
        sizes.append(size)
    print("names: {}\nsizes: {}".format(names, sizes))
    print('time for parsing OME XML: %f' %(time() - time_start))
    return names, sizes

def parse_ome_raw(filename):
    """Parses the microscope's XML file directly, pulling out salient info
    for further processing.
    
    Args:
        filename: Image file, assumed to have metadata in OME XML format.
    
    Returns:
        names: array of names of seriess within the file.
        sizes: array of tuples with dimensions for each series. Dimensions
            will be given as (time, z, y, x, channels).
        resolution: array of resolutions, also known as scaling, in the same
            dimensions as sizes.
        magnification: Objective magnification.
        zoom: Zoom level.
        pixel_type: Pixel data type as a string.
    """
    array_order = "TZYXC" # desired dimension order
    names, sizes, resolutions = [], [], []
    # names for sizes in all dimensions
    size_tags = ["Size" + c for c in array_order]
    # names for resolutions only in XYZ dimensions
    spatial_array_order = [c for c in array_order if c in "XYZ"]
    res_tags = ["PhysicalSize" + c for c in spatial_array_order]
    zoom = 1
    magnification = 1
    pixel_type = None
    metadata = bf.get_omexml_metadata(filename)
    metadata_root = et.ElementTree.fromstring(metadata)
    for child in metadata_root:
        # tag name is at end of a long string of other identifying info
        print("tag: {}".format(child.tag))
        if child.tag.endswith("Instrument"):
            # microscope info
            for grandchild in child:
                if grandchild.tag.endswith("Detector"):
                    zoom = float(grandchild.attrib["Zoom"])
                elif grandchild.tag.endswith("Objective"):
                    magnification = float(grandchild.attrib["NominalMagnification"])
            print("zoom: {}, magnification: {}".format(zoom, magnification))
        elif child.tag.endswith("Image"):
            # image file info
            names.append(child.attrib["Name"])
            for grandchild in child:
                if grandchild.tag.endswith("Pixels"):
                    att = grandchild.attrib
                    sizes.append(tuple([int(att[t]) for t in size_tags]))
                    resolutions.append(tuple([float(att[t]) for t in res_tags]))
                    # assumes pixel type is same for all images
                    if pixel_type is None:
                        pixel_type = att["Type"]
                        print("pixel_type: {}".format(pixel_type))
    print("names: {}".format(names))
    print("sizes: {}".format(sizes))
    print("resolutions: {}".format(resolutions))
    return names, sizes, resolutions, magnification, zoom, pixel_type

def find_sizes(filename):
    """Finds image size information using the ImageReader using Bioformats'
    wrapper to access a small subset of image properities.
    
    Args:
        filename: Image file, assumed to have metadata in OME XML format.
    
    Returns:
        sizes: array of tuples with dimensions for each series. Dimensions
            will be given as (time, z, y, x, channels).
    """
    time_start = time()
    sizes = []
    with bf.ImageReader(filename) as rdr:
        format_reader = rdr.rdr
        count = format_reader.getSeriesCount()
        for i in range(count):
            format_reader.setSeries(i)
            size = (format_reader.getSizeT(), format_reader.getSizeZ(), 
                    format_reader.getSizeY(), format_reader.getSizeX(), 
                    format_reader.getSizeC())
            print(size)
            sizes.append(size)
        pixel_type = format_reader.getPixelType()
        dtype = PIXEL_DTYPE[pixel_type]
        print("pixel type: {}, dtype: {}".format(pixel_type, dtype))
    print('time for finding sizes: %f' %(time() - time_start))
    return sizes, dtype

def _make_filenames(filename, series, modifier="", ext="czi"):
    filename_base = filename_to_base(filename, series, modifier, ext)
    print("filename_base: {}".format(filename_base))
    filename_image5d_npz = filename_base + SUFFIX_IMAGE5D
    filename_info_npz = filename_base + SUFFIX_INFO
    return filename_image5d_npz, filename_info_npz

def filename_to_base(filename, series, modifier="", ext="czi"):
    return filename.replace("." + ext, "_") + modifier + str(series).zfill(5)

def _save_image_info(filename_info_npz, names, sizes, resolutions, 
                     magnification, zoom, pixel_type, near_min, near_max, 
                     scaling=None, plane=None):
    outfile_info = open(filename_info_npz, "wb")
    time_start = time()
    np.savez(outfile_info, ver=IMAGE5D_NP_VER, names=names, sizes=sizes, 
             resolutions=resolutions, 
             magnification=magnification, zoom=zoom, 
             pixel_type=pixel_type, near_min=near_min, 
             near_max=near_max, scaling=scaling, plane=plane)
    outfile_info.close()
    print("info file saved to {}".format(filename_info_npz))
    print("file save time: {}".format(time() - time_start))
    
    # reload and show info file contents
    output = np.load(filename_info_npz)
    for key, value in output.items():
        print("{}: {}".format(key, value))
    output.close()

def _update_image5d_np_ver(curr_ver, image5d, info, filename_info_npz):
    if curr_ver >= IMAGE5D_NP_VER:
        # no updates necessary
        return False
    
    # update info
    info_up = dict(info)
    if curr_ver <= 10:
        # ver 10 -> 11
        # no change except ver since most likely won't encounter any difference
        pass
    
    if curr_ver <= 11:
        # ver 11 -> 12
        if info["pixel_type"] != image5d.dtype:
            # Numpy tranpositions did not update pixel type and min/max
            info_up["pixel_type"] = image5d.dtype
            info_up["near_min"], info_up["near_max"] = np.percentile(
                image5d, (0.5, 99.5))
            print("updated pixel type to {}, near_min to {}, near_max to {}"
                  .format(info_up["pixel_type"], info_up["near_min"], 
                          info_up["near_max"]))
    
    if curr_ver <= 12:
        # ver 12 -> 13
        
        lows = [info_up["near_min"]]
        highs = [info_up["near_max"]]
        scaling = None
        
        # assumed that 2nd filename given is the original file from which to 
        # calculate exact scaling
        if len(config.filenames) > 1:
            image5d_orig = read_file(
                config.filenames[1], config.series, update_info=False)
            scaling = calc_scaling(image5d_orig, image5d)
            # image5d is a scaled, smaller image, so bounds will be 
            # calculated since the calculation requires loading full image 
            # into memory; otherwise, defer to re-importing the image
            lows, highs = _calc_intensity_bounds(image5d)
        elif image5d.ndim >= 5:
            # default to simply converting the existing scalar to a list 
            # of repeated scalars
            channels = image5d.shape[4]
            print("channels: {}".format(channels))
            lows = [lows[0] for i in range(channels)]
            highs = [highs[0] for i in range(channels)]
        info_up["near_min"] = lows
        info_up["near_max"] = highs
        info_up["scaling"] = scaling
        info_up["plane"] = plot_2d.plane
    
    # save updated info
    info_up["ver"] = IMAGE5D_NP_VER
    outfile_info = open(filename_info_npz, "wb")
    np.savez(outfile_info, **info_up)
    outfile_info.close()
    
    return True

def read_file(filename, series, load=True, z_max=-1, 
              offset=None, size=None, channel=None, return_info=False, 
              import_if_absent=True, update_info=True):
    """Reads in an imaging file.
    
    Loads a Numpy image if available as determined by 
    :func:``_make_filenames``. An offset and size can be given to load an 
    only an ROI of the image. If the corresponding Numpy image cannot be 
    found, one will be generated from the given source image. For TIFF images, 
    multiple channels will assume to be stored in separate files with 
    :const:``CHANNEL_SEPARATOR`` followed by an integer corresponding to the 
    channel number (0-based indexing).
    
    Args:
        filename: Image file, assumed to have metadata in OME XML format.
        series: Series index to load.
        load: If True, attempts to load a Numpy array from the same 
            location and name except for ".npz" appended to the end 
            (default). The array can be accessed as "output['image5d']".
        z_max: Number of z-planes to load, or -1 if all should be loaded
            (default).
        offset: Tuple of offset given as (x, y, z) from which to start
            loading z-plane (x, y ignored for now). If Numpy image info already 
            exists, this tuple will be used to load only an ROI of the image. 
            If importing a new Numpy image, offset[2] will be used an a 
            z-offset from which to start importing. Defaults to None.
        size: Tuple of ROI size given as (x, y, z). If Numpy image info already 
            exists, this tuple will be used to load only an ROI of the image. 
            Defaults to None.
        channel: Channel number, currently used only to load a channel when 
            a Numpy ROI image exists. Otherwise, all channels available will 
            be imported into a new Numpy image. Defaults to None.
        return_info: True if the Numpy info file should be returned for a 
            dictionary of image properties; defaults to False.
        import_if_absent: True if the image should be imported into a Numpy 
            image if it does not exist; defaults to True.
        update_info: True if the associated image5d info file should be 
            updated; defaults to True.
    
    Returns:
        image5d, the array of image data. If ``return_info`` is True, a 
        second value a dictionary of image properties will be returned.
    """
    ext = lib_clrbrain.get_filename_ext(filename)
    filename_image5d_npz, filename_info_npz = _make_filenames(
        filename, series, ext=ext)
    if load:
        try:
            time_start = time()
            load_info = True
            while load_info:
                # image info, such as microscopy data
                output = np.load(filename_info_npz)
                '''
                # convert old monolithic archive into 2 separate archives
                filename_npz = filename + str(series).zfill(5) + ".npz" # old format
                output = np.load(filename_npz)
                outfile_image5d = open(filename_image5d_npz, "wb")
                np.save(outfile_image5d, output["image5d"])
                outfile_image5d.close()
                outfile_info = open(filename_info_npz, "wb")
                np.savez(outfile_info, names=output["names"], sizes=output["sizes"], 
                         resolutions=output["resolutions"], magnification=output["magnification"], 
                         zoom=output["zoom"], pixel_type=output["pixel_type"])
                outfile_info.close()
                print('file opening time: %f' %(time() - time_start))
                return
                '''
                image5d_ver_num = -1
                try:
                    # find the info version number
                    image5d_ver_num = output["ver"]
                    print("loaded image5d version number {}"
                          .format(image5d_ver_num))
                except KeyError:
                    print("could not find image5d version number")
                try:
                    names = output["names"]
                    print("names: {}".format(names))
                except KeyError:
                    print("could not find names")
                try:
                    sizes = output["sizes"]
                    print("sizes {}".format(sizes))
                except KeyError:
                    print("could not find sizes")
                try:
                    detector.resolutions = output["resolutions"]
                    print("set resolutions to {}".format(detector.resolutions))
                except KeyError:
                    print("could not find resolutions")
                try:
                    detector.magnification = output["magnification"]
                    print("magnification: {}".format(detector.magnification))
                except KeyError:
                    print("could not find magnification")
                try:
                    detector.zoom = output["zoom"]
                    print("zoom: {}".format(detector.zoom))
                except KeyError:
                    print("could not find zoom")
                # TODO: remove since stored in image5d?
                try:
                    pixel_type = output["pixel_type"]
                    print("pixel type is {}".format(pixel_type))
                except KeyError:
                    print("could not find pixel_type")
                try:
                    plot_3d.near_min = output["near_min"]
                    print("set near_min to {}".format(plot_3d.near_min))
                except KeyError:
                    print("could not find near_max")
                try:
                    plot_3d.near_max = output["near_max"]
                    print("set near_max to {}".format(plot_3d.near_max))
                    plot_2d.vmax_overview = plot_3d.near_max * 1.1
                    print("Set vmax_overview to {}".format(plot_2d.vmax_overview))
                except KeyError:
                    print("could not find near_max")
                
                # load original image, using mem-mapped accessed for the image
                # file to minimize memory requirement, only loading on-the-fly
                image5d = np.load(filename_image5d_npz, mmap_mode="r")
                if offset is not None and size is not None:
                    # simplifies to reducing the image to a subset as an ROI if 
                    # offset and size given
                    image5d = plot_3d.prepare_roi(image5d, size, offset)
                    image5d = importer.roi_to_image5d(image5d)
                '''
                max_range = 0
                if plot_3d.near_max is not None:
                    #print("dtype: {}".format(image5d.dtype))
                    if np.issubdtype(image5d.dtype, np.integer):
                        max_range = np.iinfo(image5d.dtype).max
                    elif np.issubdtype(image5d.dtype, np.float):
                        max_range = np.ninfo(image5d.dtype).max
                    if max_range != 0:
                        plot_2d.vmax_overview = plot_3d.near_max / max_range
                '''
                if update_info:
                    load_info = _update_image5d_np_ver(
                        image5d_ver_num, image5d, output, filename_info_npz)
                else:
                    load_info = False
            if return_info:
                return image5d, output
            return image5d
        except IOError as e:
            print(e)
            if import_if_absent:
                print("will attempt to reload {}".format(filename))
            else:
                if return_info:
                    return None, output
                return None
    start_jvm()
    time_start = time()
    image5d = None
    shape = None
    load_channel = 0
    if offset is None:
        offset = (0, 0, 0) # (x, y, z)
    name = os.path.basename(filename)
    filenames = sorted(glob.glob(
        os.path.splitext(filename)[0] + CHANNEL_SEPARATOR + "*"))
    if len(filenames) == 0:
        filenames.append(filename)
    print(filenames)
    num_files = len(filenames)
    if ext == "tiff" or ext == "tif":
        # import multipage TIFFs
        print("Loading multipage TIFF...")
        
        if detector.resolutions is None:
            raise IOError("Could not import {}. Please specify resolutions, "
                          "magnification, and zoom.".format(filenames[0]))
        sizes, dtype = find_sizes(filenames[0])
        shape = list(sizes[0])
        if num_files > 1:
            shape[-1] = num_files
        if shape[-1] == 1:
            shape = shape[:-1]
        shape = tuple(shape)
        print(shape)
    else:
        # default import mode, which assumes parseable OME header, tested 
        # on CZI files
        print("Loading {} file...".format(ext))
        
        # parses the XML tree directly
        names, sizes, detector.resolutions, detector.magnification, \
            detector.zoom, pixel_type = parse_ome_raw(filenames[0])
        shape = sizes[series]
        if z_max != -1:
            shape[1] = z_max
        #dtype = getattr(np, pixel_type)
        # generate image stack dimensions based on whether channel dim exists
        if shape[4] <= 1:
            # for 1 channel images, remove channel dimension since redundant
            shape = shape[:-1]
            load_channel = 0
        else:
            # load all channels
            load_channel = None
        name = names[series]
    near_mins = []
    near_maxs = []
    for img_path in filenames:
        # multiple images for multichannel TIFF files, but only single 
        # image if integrated CZI
        rdr = bf.ImageReader(img_path, perform_init=True)
        lows = []
        highs = []
        if num_files > 1:
            channel_num = int(
                os.path.splitext(img_path)[0].split(CHANNEL_SEPARATOR)[1])
            print("adding {} to channel {}".format(img_path, channel_num))
        for t in range(shape[0]):
            for z in range(shape[1]):
                print("loading planes from [{}, {}]".format(t, z))
                img = rdr.read(z=(z + offset[2]), t=t, c=load_channel,
                               series=series, rescale=False)
                if image5d is None:
                    # open file as memmap to directly output to disk, which is much 
                    # faster than outputting to RAM and saving to disk
                    image5d = np.lib.format.open_memmap(
                        filename_image5d_npz, mode="w+", dtype=img.dtype, 
                        shape=shape)
                    print("setting image5d array for series {} with shape: {}"
                          .format(series, image5d.shape))
                # near max/min bounds per channel for the given plane
                low, high = _calc_intensity_bounds(img, dim_channel=2)
                lows.append(low)
                highs.append(high)
                if num_files > 1:
                    # squeeze plane inside if separate file per channel
                    image5d[t, z, :, :, channel_num] = img
                else:
                    image5d[t, z] = img
        if num_files > 1:
            # get min/max from list of 1-element arrays
            near_mins.append(min(lows)[0])
            near_maxs.append(max(highs)[0])
        else:
            # get min/max from columns of 2D array
            near_mins = np.amin(np.array(lows), 0)
            near_maxs = np.amax(np.array(highs), 0)
    print("file import time: {}".format(time() - time_start))
    time_start = time()
    image5d.flush() # may not be necessary but ensure contents to disk
    print("flush time: {}".format(time() - time_start))
    #print("lows: {}, highs: {}".format(lows, highs))
    # TODO: consider saving resolutions as 1D rather than 2D array
    # with single resolution tuple
    _save_image_info(filename_info_npz, [name], 
                     [shape], [detector.resolutions[series]], 
                     detector.magnification, detector.zoom, 
                     image5d.dtype, near_mins, near_maxs)
    return image5d

def import_dir(path):
    files = sorted(glob.glob(path))
    #files.sort(key=lambda f: int("".join(filter(str.isdigit, f))))
    num_files = len(files)
    if num_files < 1:
        return None
    name = os.path.dirname(files[0])
    filename_image5d_npz, filename_info_npz = _make_filenames(name + ".czi", 0)
    image5d = None
    lows = []
    highs = []
    i = 0
    for f in files:
        print("importing {}".format(f))
        img = io.imread(f)
        if image5d is None:
            #image5d = np.empty((1, len(files), *img.shape))
            image5d = np.lib.format.open_memmap(
                filename_image5d_npz, mode="w+", dtype=img.dtype, 
                shape=(1, len(files), *img.shape))
        image5d[0, i] = img
        low, high = np.percentile(img, (0.5, 99.5))
        lows.append(low)
        highs.append(high)
        i += 1
    _save_image_info(filename_info_npz, [name], 
                     [image5d.shape], detector.resolutions, 
                     detector.magnification, detector.zoom, image5d.dtype,
                     [min(lows)], [max(highs)])
    return image5d

def _rescale_sub_roi(coord, sub_roi, rescale, multichannel):
    rescaled = transform.rescale(
        sub_roi, rescale, mode="reflect", multichannel=multichannel)
    return coord, rescaled

def make_modifier_plane(plane):
    return "plane{}".format(plane.upper())

def make_modifier_scale(scale):
    return "scale{}".format(scale)

def _calc_intensity_bounds(image5d, lower=0.5, upper=99.5, dim_channel=4):
    """Calculate image intensity boundaries for the given percentiles, 
    including boundaries for each channel in multichannel images.
    
    Assume that the image will be small enough to load entirely into 
    memory rather than calculating bounds plane-by-plane. Also assume that 
    bounds for all channels will be calculated.
    
    Args:
        image5d: Image as a 5D (t, z, y, x, c) array, or a 4D array if only 
            1 channel is present.
        lower: Lower bound as a percentile.
        upper: Upper bound as a percentile.
    
    Returns:
        Tuple of ``lows`` and ``highs``, each of which is a list of the 
        low and high values at the given percentile cutoffs for each channel.
    """
    multichannel, channels = plot_3d.setup_channels(image5d, None, dim_channel)
    lows = []
    highs = []
    for i in channels:
        image5d_show = image5d[..., i] if multichannel else image5d
        low, high = np.percentile(image5d_show, (lower, upper))
        lows.append(low)
        highs.append(high)
    return lows, highs

def transpose_npy(filename, series, plane=None, rescale=None):
    """Transpose Numpy NPY saved arrays into new planar orientations and/or 
    rescaled sizes.
    
    Saves file to a new NPY archive with "transposed" inserted just prior
    to the series name so that "transposed" can be appended to the original
    filename for future loading within Clrbrain. Files are saved through 
    memmap-based arrays to minimize RAM usage.
    
    Args:
        filename: Full file path in :attribute:cli:`filename` format.
        series: Series within multi-series file.
        plane: Planar orientation (see :attribute:plot_2d:`PLANES`). Defaults 
            to None, in which case no planar transformation will occur.
        rescale: Rescaling factor. Defaults to None, in which case no 
            rescaling will occur. Rescaling takes place in multiplrocessing.
    """
    time_start = time()
    image5d, info = read_file(filename, series, return_info=True)
    sizes = info["sizes"]
    ext = lib_clrbrain.get_filename_ext(filename)
    modifier = ""
    if plane is not None:
        modifier = make_modifier_plane(plane) + "_"
    if rescale is not None:
        modifier += make_modifier_scale(rescale) + "_"
    filename_image5d_npz, filename_info_npz = _make_filenames(
        filename, series, modifier=modifier, ext=ext)
    offset = 0 if image5d.ndim <= 3 else 1
    multichannel = image5d.ndim >=5
    image5d_swapped = image5d
    
    if plane is not None and plane != plot_2d.PLANE[0]:
        # swap z-y to get (y, z, x) order for xz orientation
        image5d_swapped = np.swapaxes(image5d_swapped, offset, offset + 1)
        detector.resolutions[0] = lib_clrbrain.swap_elements(
            detector.resolutions[0], 0, 1)
        if plane == plot_2d.PLANE[2]:
            # swap new y-x to get (x, z, y) order for yz orientation
            image5d_swapped = np.swapaxes(image5d_swapped, offset, offset + 2)
            detector.resolutions[0] = lib_clrbrain.swap_elements(
                detector.resolutions[0], 0, 2)
    
    scaling = None
    if rescale is not None:
        rescaled = image5d_swapped
        # TODO: generalize for more than 1 preceding dimension?
        if offset > 0:
            rescaled = rescaled[0]
        #max_pixels = np.multiply(np.ones(3), 100)
        max_pixels = [100, 500, 500]
        
        # rescale in chunks with multiprocessing
        overlap = np.zeros(3).astype(np.int)
        sub_rois, _ = chunking.stack_splitter(rescaled, max_pixels, overlap)
        pool = mp.Pool()
        pool_results = []
        for z in range(sub_rois.shape[0]):
            for y in range(sub_rois.shape[1]):
                for x in range(sub_rois.shape[2]):
                    coord = (z, y, x)
                    pool_results.append(
                        pool.apply_async(
                            _rescale_sub_roi, 
                            args=(coord, sub_rois[coord], rescale, 
                                  multichannel)))
        for result in pool_results:
            coord, sub_roi = result.get()
            print("replacing sub_roi at {} of {}"
                  .format(coord, np.add(sub_rois.shape, -1)))
            sub_rois[coord] = sub_roi
        
        pool.close()
        pool.join()
        rescaled_shape = chunking.get_split_stack_total_shape(sub_rois, overlap)
        if offset > 0:
            rescaled_shape = np.concatenate(([1], rescaled_shape))
        if multichannel:
            rescaled_shape = np.concatenate((rescaled_shape, [rescaled.shape[-1]]))
        print("rescaled_shape: {}".format(rescaled_shape))
        # rescale chunks directly into memmap-backed array to minimize RAM usage
        image5d_transposed = np.lib.format.open_memmap(
            filename_image5d_npz, mode="w+", dtype=sub_rois[0, 0, 0].dtype, 
            shape=tuple(rescaled_shape))
        chunking.merge_split_stack2(sub_rois, overlap, offset, image5d_transposed)
        
        detector.resolutions = np.multiply(detector.resolutions, 1 / rescale)
        sizes[0] = rescaled_shape
        scaling = calc_scaling(image5d_swapped, image5d_transposed)
    else:
        # transfer directly to memmap-backed array
        image5d_transposed = np.lib.format.open_memmap(
            filename_image5d_npz, mode="w+", dtype=image5d_swapped.dtype, 
            shape=image5d_swapped.shape)
        if plane == plot_2d.PLANE[1] or plane == plot_2d.PLANE[2]:
            # flip upside-down if re-orienting planes
            if offset:
                image5d_transposed[0, :] = np.fliplr(image5d_swapped[0, :])
            else:
                image5d_transposed[:] = np.fliplr(image5d_swapped[:])
        else:
            image5d_transposed[:] = image5d_swapped[:]
        sizes[0] = image5d_swapped.shape
    #print("new shape: {}".format(sizes[0]))
    print("detector.resolutions: {}".format(detector.resolutions))
    print("sizes: {}".format(sizes))
    image5d.flush()
    _save_image_info(
        filename_info_npz, info["names"], sizes, detector.resolutions, 
        info["magnification"], info["zoom"], image5d_transposed.dtype, 
        *_calc_intensity_bounds(image5d_transposed), scaling, plane)
    print("saved transposed file to {} with shape {}".format(
        filename_image5d_npz, image5d_transposed.shape))
    print("time elapsed (s): {}".format(time() - time_start))

def save_np_image(image, filename, series):
    """Save Numpy image to file.
    
    Assumes that the image or another image with similar parameters 
    has already been loaded so that the info file 
    can be constructed from the currently set parameters. Near min/max values 
    are generated from the entire image.
    
    Args:
        image: Numpy array.
        filename: Filename of original file, which will be passed to 
            :func:``_make_filenames`` to create output filenames.
        series: Image series.
    """
    filename_image5d_npz, filename_info_npz = _make_filenames(
        filename, series, ext=lib_clrbrain.get_filename_ext(filename))
    out_file = open(filename_image5d_npz, "wb")
    np.save(out_file, image)
    out_file.close()
    lows, highs = _calc_intensity_bounds(image5d)
    _save_image_info(
        filename_info_npz, [os.path.basename(filename)], [image.shape], 
        detector.resolutions, detector.magnification, detector.zoom, 
        image.dtype, lows, highs)

def calc_scaling(image5d, scaled):
    shape = image5d.shape
    scaled_shape = scaled.shape
    # remove time dimension
    if image5d.ndim >=4:
        shape = shape[1:4]
    if scaled.ndim >=4:
        scaled_shape = scaled_shape[1:4]
    scaling = np.divide(scaled_shape[0:3], shape[0:3])
    print("image scaling compared to image5d: {}".format(scaling))
    return scaling

def roi_to_image5d(roi):
    return np.array([roi])

if __name__ == "__main__":
    print("Clrbrain importer manipulations")
    from clrbrain import cli
    cli.main(True)
