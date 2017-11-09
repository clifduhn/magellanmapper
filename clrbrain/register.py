#!/bin/bash
# Image registration
# Author: David Young, 2017
"""Register images to one another.
"""

import os
import json
from pprint import pprint
import SimpleITK as sitk
import numpy as np

from clrbrain import cli
from clrbrain import detector
from clrbrain import importer
from clrbrain import lib_clrbrain
from clrbrain import plot_2d

IMG_ATLAS = "atlasVolume.mhd"
IMG_LABELS = "annotation.mhd"

def _reg_out_path(file_path, reg_name):
    """Generate a path for a file registered to another file.
    
    Args:
        file_name: Full path of file registered to.
        reg_name: Filename alone of registered file.
    
    Returns:
        Full path with the registered filename including extension at the end.
    """
    file_path_base = importer.filename_to_base(file_path, cli.series)
    return file_path_base + "_" + reg_name

def _translation_adjust(orig, transformed, translation):
    """Adjust translation based on differences in scaling between original 
    and transformed images to allow the translation to be applied to the 
    original image.
    
    Assumes (x, y, z) order for consistency with SimpleITK since this method 
    operates on SimpleITK format images.
    
    Args:
        orig: Original image in SimpleITK format.
        transformed: Transformed image in SimpleITK format.
        translation: Translation in (x, y, z) order, taken from transform 
            parameters and scaled to the transformed images's spacing.
    
    Returns:
        The adjusted translation in (x, y, z) order.
    """
    # TODO: need to check which space the TransformParameter is referring to 
    # and how to scale it since the adjusted translation does not appear to 
    # be working yet
    orig_origin = orig.GetOrigin()
    transformed_origin = transformed.GetOrigin()
    origin_diff = np.subtract(transformed_origin, orig_origin)
    print("orig_origin: {}, transformed_origin: {}, origin_diff: {}"
          .format(orig_origin, transformed_origin, origin_diff))
    orig_size = orig.GetSize()
    transformed_size = transformed.GetSize()
    size_ratio = np.divide(orig_size, transformed_size)
    print("orig_size: {}, transformed_size: {}, size_ratio: {}"
          .format(orig_size, transformed_size, size_ratio))
    translation_adj = np.multiply(translation, size_ratio)
    #translation_adj = np.add(translation_adj, origin_diff)
    print("translation_adj: {}".format(translation_adj))
    return translation_adj

def _show_overlays(imgs, translation, fixed_file):
    """Shows overlays via :func:plot_2d:`plot_overlays_reg`.
    
    Args:
        imgs: List of images in Numpy format
        translation: Translation in (z, y, x) format for Numpy consistency.
        fixed_file: Path to fixed file to get title.
    """
    cmaps = ["Blues", "Oranges", "prism"]
    #plot_2d.plot_overlays(imgs, z, cmaps, os.path.basename(fixed_file), aspect)
    #translation = None # TODO: not using translation parameters for now
    plot_2d.plot_overlays_reg(*imgs, *cmaps, translation, os.path.basename(fixed_file))

def _handle_transform_file(fixed_file, transform_param_map=None):
    base_name = _reg_out_path(fixed_file, "")
    filename = base_name.rsplit(".", 1)[0] + "transform.txt"
    param_map = None
    if transform_param_map is None:
        param_map = sitk.ReadParameterFile(filename)
    else:
        sitk.WriteParameterFile(transform_param_map[0], filename)
        param_map = transform_param_map[0]
    transform = np.array(param_map["TransformParameters"]).astype(np.float)
    spacing = np.array(param_map["Spacing"]).astype(np.float)
    #spacing = [16, 16, 20]
    translation = np.divide(transform, spacing)
    print("transform: {}, spacing: {}, translation: {}"
          .format(transform, spacing, translation))
    return param_map, translation

def _mirror_labels(img):
    """Mirror labels across the z plane.
    
    Assumes that the image is empty from the far z planes toward the middle 
    but not necessarily the exact middle. Finds the first plane that doesn't 
    have any intensity values and sets this position as the mirror plane.
    
    Args:
        img: Image in SimpleITK format.
    
    Returns:
        The mirrored image in the same dimensions, origin, and spacing as the 
        original image.
    """
    img_np = sitk.GetArrayFromImage(img)
    tot_planes = len(img_np)
    i = tot_planes
    # need to work backward since the starting z-planes may also be empty
    for plane in img_np[::-1]:
        if not np.allclose(plane, 0):
            break
        i -= 1
    if i <= tot_planes and i >= 0:
        # if a empty planes at end, fill the empty space with the preceding 
        # planes in mirrored fashion
        remaining_planes = tot_planes - i
        end = i - remaining_planes
        if end < 0:
            end = 0
            remaining_planes = i
        print("i: {}, end: {}, remaining_planes: {}, tot_planes: {}"
              .format(i, end, remaining_planes, tot_planes))
        img_np[i:i+remaining_planes] = img_np[i-1:end-1:-1]
    else:
        # skip mirroring if no planes are empty or only first plane is empty
        print("nothing to mirror")
        return img
    img_reflected = sitk.GetImageFromArray(img_np)
    img_reflected.SetSpacing(img.GetSpacing())
    img_reflected.SetOrigin(img.GetOrigin())
    return img_reflected

def transpose_img(img_sitk, plane, flip_horiz):
    img = sitk.GetArrayFromImage(img_sitk)
    spacing = img_sitk.GetSpacing()
    origin = img_sitk.GetOrigin()
    transposed = img
    if plane is not None and plane != plot_2d.PLANE[0]:
        # swap z-y to get (y, z, x) order for xz orientation
        transposed = np.swapaxes(transposed, 0, 1)
        # sitk convension is opposite of numpy with (x, y, z) order
        spacing = lib_clrbrain.swap_elements(spacing, 1, 2)
        origin = lib_clrbrain.swap_elements(origin, 1, 2)
        if plane == plot_2d.PLANE[1]:
            # rotate
            transposed = transposed[..., ::-1]
            transposed = np.swapaxes(transposed, 1, 2)
        elif plane == plot_2d.PLANE[2]:
            # swap new y-x to get (x, z, y) order for yz orientation
            transposed = np.swapaxes(transposed, 0, 2)
            spacing = lib_clrbrain.swap_elements(spacing, 0, 2)
            origin = lib_clrbrain.swap_elements(origin, 0, 2)
            # rotate
            transposed = np.swapaxes(transposed, 1, 2)
            spacing = lib_clrbrain.swap_elements(spacing, 0, 1)
        if plane == plot_2d.PLANE[1] or plane == plot_2d.PLANE[2]:
            # flip upside-down
            transposed[:] = np.flipud(transposed[:])
            if flip_horiz:
                transposed = transposed[..., ::-1]
        else:
            transposed[:] = transposed[:]
    transposed = sitk.GetImageFromArray(transposed)
    transposed.SetSpacing(spacing)
    transposed.SetOrigin(origin)
    return transposed

def register(fixed_file, moving_file_dir, flip_horiz=False, show_imgs=True, 
             write_imgs=False, name_prefix=None):
    """Registers two images to one another using the SimpleElastix library.
    
    Args:
        fixed_file: The image to register, given as a Numpy archive file to 
            be read by :importer:`read_file`.
        moving_file_dir: Directory of the atlas images, including the 
            main image and labels. The atlas was chosen as the moving file
            since it is likely to be lower resolution than the Numpy file.
    """
    if name_prefix is None:
        name_prefix = fixed_file
    image5d = importer.read_file(fixed_file, cli.series)
    roi = image5d[0, ...] # not using time dimension
    if flip_horiz:
        roi = roi[..., ::-1]
    fixed_img = sitk.GetImageFromArray(roi)
    spacing = detector.resolutions[0]
    #print("spacing: {}".format(spacing))
    fixed_img.SetSpacing(spacing[::-1])
    fixed_img.SetOrigin([0, 0, -roi.shape[0] // 2])
    #fixed_img = sitk.RescaleIntensity(fixed_img)
    #fixed_img = sitk.Cast(fixed_img, sitk.sitkUInt32)
    #sitk.Show(transpose_img(fixed_img, plot_2d.plane, flip_horiz))
    
    moving_file = os.path.join(moving_file_dir, IMG_ATLAS)
    moving_img = sitk.ReadImage(moving_file)
    
    print(fixed_img)
    print(moving_img)
    
    elastix_img_filter = sitk.ElastixImageFilter()
    elastix_img_filter.SetFixedImage(fixed_img)
    elastix_img_filter.SetMovingImage(moving_img)
    param_map_vector = sitk.VectorOfParameterMap()
    param_map = sitk.GetDefaultParameterMap("translation")
    
    param_map["MaximumNumberOfIterations"] = ["2048"]
    param_map_vector.append(param_map)
    param_map = sitk.GetDefaultParameterMap("affine")
    '''
    # TESTING: minimal registration
    param_map["MaximumNumberOfIterations"] = ["2"]
    '''
    
    param_map_vector.append(param_map)
    elastix_img_filter.SetParameterMap(param_map_vector)
    elastix_img_filter.PrintParameterMap()
    transform = elastix_img_filter.Execute()
    transformed_img = elastix_img_filter.GetResultImage()
    
    transform_param_map = elastix_img_filter.GetTransformParameterMap()
    _, translation = _handle_transform_file(name_prefix, transform_param_map)
    translation = _translation_adjust(moving_img, transformed_img, translation)
    
    # apply transformation to label files
    transformix_img_filter = sitk.TransformixImageFilter()
    transformix_img_filter.SetTransformParameterMap(transform_param_map)
    img_files = (IMG_LABELS, )
    imgs_transformed = []
    for img_file in img_files:
        img = sitk.ReadImage(os.path.join(moving_file_dir, img_file))
        # ABA only gives half of atlas so need to mirror one side to other
        img = _mirror_labels(img)
        transformix_img_filter.SetMovingImage(img)
        transformix_img_filter.Execute()
        result_img = transformix_img_filter.GetResultImage()
        result_img = sitk.Cast(result_img, img.GetPixelID())
        imgs_transformed.append(result_img)
        print(result_img)
    
    if show_imgs:
        # show individual SimpleITK images in default viewer
        sitk.Show(fixed_img)
        sitk.Show(moving_img)
        sitk.Show(transformed_img)
        for img in imgs_transformed:
            sitk.Show(img)
    
    if write_imgs:
        # write atlas and labels files, transposed according to plane setting
        imgs_names = (IMG_ATLAS, IMG_LABELS)
        imgs_write = [transformed_img, imgs_transformed[0]]
        for i in range(len(imgs_write)):
            out_path = _reg_out_path(name_prefix, imgs_names[i])
            img = transpose_img(imgs_write[i], plot_2d.plane, flip_horiz)
            print("writing {}".format(out_path))
            sitk.WriteImage(img, out_path, False)

    # show 2D overlay for registered images
    imgs = [
        roi, 
        sitk.GetArrayFromImage(moving_img), 
        sitk.GetArrayFromImage(transformed_img), 
        sitk.GetArrayFromImage(imgs_transformed[0])]
    _show_overlays(imgs, translation[::-1], fixed_file)
    
def overlay_registered_imgs(fixed_file, moving_file_dir, flip_horiz=False, name_prefix=None):
    """Shows overlays of previously saved registered images.
    
    Should be run after :func:`register` has written out images in default
    (xy) orthogonal orientation.
    
    Args:
        fixed_file: Path to the fixed file.
        moving_file_dir: Moving files directory, from which the original
            atlas will be retrieved.
        flip_horiz: If true, will flip the fixed file horizontally first; 
            defaults to False.
        name_prefix: Path with base name where registered files are located; 
            defaults to None, in which case the fixed_file path will be used.
    """
    if name_prefix is None:
        name_prefix = fixed_file
    image5d = importer.read_file(fixed_file, cli.series)
    roi = image5d[0, ...] # not using time dimension
    if flip_horiz:
        roi = roi[..., ::-1]
    out_path = os.path.join(moving_file_dir, IMG_ATLAS)
    print("Reading in {}".format(out_path))
    moving_sitk = sitk.ReadImage(out_path)
    moving_img = sitk.GetArrayFromImage(moving_sitk)
    out_path = _reg_out_path(name_prefix, IMG_ATLAS)
    print("Reading in {}".format(out_path))
    transformed_sitk = sitk.ReadImage(out_path)
    transformed_img = sitk.GetArrayFromImage(transformed_sitk)
    out_path = _reg_out_path(name_prefix, IMG_LABELS)
    print("Reading in {}".format(out_path))
    labels_img = sitk.GetArrayFromImage(sitk.ReadImage(out_path))
    imgs = [roi, moving_img, transformed_img, labels_img]
    _, translation = _handle_transform_file(name_prefix)
    translation = _translation_adjust(moving_sitk, transformed_sitk, translation)
    _show_overlays(imgs, translation[::-1], fixed_file)

def load_labels(fixed_file):
    labels_path = _reg_out_path(fixed_file, IMG_ATLAS)
    labels_img = sitk.ReadImage(labels_path)
    print("loaded labels image from {}".format(labels_path))
    return sitk.GetArrayFromImage(labels_img)

def reg_scaling(image5d, reg):
    shape = image5d.shape
    if image5d.ndim >=4:
        shape = shape[1:4]
    scaling = np.divide(reg.shape[0:3], shape[0:3])
    print("registered image scaling compared to image5d: {}".format(scaling))
    return scaling

def load_labels_ref(path):
    labels_ref = None
    with open(path, "r") as f:
        labels_ref = json.load(f)
        #pprint(labels_ref)
    return labels_ref

if __name__ == "__main__":
    print("Clrbrain image registration")
    cli.main(True)
    # run with --plane xy to generate non-transposed images before comparing 
    # orthogonal views in overlay_registered_imgs, then run with --plane xz
    # to re-transpose to original orientation for mapping locations
    #register(cli.filenames[0], cli.filenames[1], flip_horiz=True, show_imgs=True, write_imgs=True, name_prefix=cli.filenames[2])
    #register(cli.filenames[0], cli.filenames[1], flip_horiz=True, show_imgs=False)
    #overlay_registered_imgs(cli.filenames[0], cli.filenames[1], flip_horiz=True, name_prefix=cli.filenames[2])
    for plane in plot_2d.PLANE:
        plot_2d.plane = plane
        overlay_registered_imgs(cli.filenames[0], cli.filenames[1], flip_horiz=True, name_prefix=cli.filenames[2])
