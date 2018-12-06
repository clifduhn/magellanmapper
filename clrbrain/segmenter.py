# Segmentation methods
# Author: David Young, 2018
"""Segment regions based on blobs, labels, and underlying features.
"""

import numpy as np
from scipy import ndimage
from skimage import feature
from skimage import filters
from skimage import segmentation
from skimage import measure
from skimage import morphology

from clrbrain import config
from clrbrain import lib_clrbrain
from clrbrain import plot_3d

def _markers_from_blobs(roi, blobs):
    # use blobs as seeds by converting blobs into marker image
    markers = np.zeros(roi.shape, dtype=np.uint8)
    coords = lib_clrbrain.coords_for_indexing(blobs[:, :3].astype(int))
    markers[tuple(coords)] = 1
    markers = morphology.dilation(markers, morphology.ball(1))
    markers = measure.label(markers)
    return markers

def _carve_segs(roi, blobs):
    # carve out background from segmented area
    carved = roi
    if blobs is None:
        # clean up by using simple threshold to remove all background
        carved, _ = plot_3d.carve(carved)
    else:
        # use blobs as ellipsoids to identify background to remove; 
        # TODO: consider setting spacing in config since depends on 
        # microscopy characteristics, such as elongation from 
        # thick lightsheet
        thresholded = plot_3d.build_ground_truth(
            np.zeros(carved.shape, dtype=bool), blobs, ellipsoid=True)
        #thresholded = thresholded.astype(bool)
        carved[~thresholded] = 0
    return carved

def segment_rw(roi, channel, beta=50.0, vmin=0.6, vmax=0.65, remove_small=None, 
               erosion=None, blobs=None, get_labels=False):
    """Segments an image using the Random-Walker algorithm.
    
    Args:
        roi: Region of interest to segment.
        channel: Channel to pass to :func:``plot_3d.setup_channels``.
        beta: Random-Walker beta term.
        vmin: Values under which to exclude in markers; defaults to 0.6. 
            Ignored if ``blobs`` is given.
        vmax: Values above which to exclude in markers; defaults to 0.65. 
            Ignored if ``blobs`` is given.
        remove_small: Threshold size of small objects to remove; defaults 
            to None to ignore.
        erosion: Structuring element size for erosion; defaults 
            to None to ignore.
        blobs: Blobs to use for markers; defaults to None, in which 
            case markers will be determined based on ``vmin``/``vmax`` 
            thresholds.
        get_labels: True to measure and return labels from the 
            resulting segmentation instead of returning the segmentations 
            themselves; defaults to False.
    
    Returns:
        List of the Random-Walker segmentations for the given channels, 
        If ``get_labels`` is True, the measured labels for the segmented 
        regions will be returned instead of the segmentations themselves.
    """
    print("Random-Walker based segmentation...")
    labels = []
    walkers = []
    multichannel, channels = plot_3d.setup_channels(roi, channel, 3)
    for i in channels:
        roi_segment = roi[..., i] if multichannel else roi
        if blobs is None:
            # mark unknown pixels as 0 by distinguishing known background 
            # and foreground
            markers = np.zeros(roi_segment.shape, dtype=np.uint8)
            markers[roi_segment < vmin] = 2
            markers[roi_segment >= vmax] = 1
        else:
            # derive markers from blobs
            markers = _markers_from_blobs(roi_segment, blobs)
        
        # perform the segmentation
        walker = segmentation.random_walker(
            roi_segment, markers, beta=beta, mode="cg_mg")
        
        
        # clean up segmentation
        
        #lib_clrbrain.show_full_arrays()
        walker = _carve_segs(walker, blobs)
        if remove_small:
            # remove artifacts
            walker = morphology.remove_small_objects(walker, remove_small)
        if erosion:
            # attempt to reduce label connections by eroding
            walker = morphology.erosion(walker, morphology.octahedron(erosion))
        
        
        if get_labels:
            # label neighboring pixels to segmented regions
            # TODO: check if necessary; useful only if blobs not given?
            label = measure.label(walker, background=0)
            labels.append(label)
            #print("label:\n", label)
        
        walkers.append(walker)
        #print("walker:\n", walker)
    
    if get_labels:
        return labels
    return walkers

def segment_ws(roi, channel, thresholded=None, blobs=None): 
    """Segment an image using a compact watershed, including the option 
    to use a 3D-seeded watershed approach.
    
    Args:
        roi: ROI as a Numpy array in (z, y, x) order.
        channel: Channel to pass to :func:``plot_3d.setup_channels``.
        thresholded: Thresholded image such as a segmentation into foreground/
            background given by Random-walker (:func:``segment_rw``). 
            Defaults to None, in which case Otsu thresholding will be performed.
        blobs: Blobs as a Numpy array in [[z, y, x, ...], ...] order, which 
            are used as seeds for the watershed. Defaults to None, in which 
            case peaks on a distance transform will be used.
    
    Returns:
        List of watershed labels for each given channel, with each set 
        of labels given as an image of the same shape as ``roi``.
    """
    labels = []
    multichannel, channels = plot_3d.setup_channels(roi, channel, 3)
    for i in channels:
        roi_segment = roi[..., i] if multichannel else roi
        if thresholded is None:
            # Ostu thresholing and object separate based on local max 
            # rather than seeded watershed approach
            roi_thresh = filters.threshold_otsu(roi, 64)
            thresholded = roi > roi_thresh
        else:
            # r-w assigned 0 values to > 0 val labels
            thresholded = thresholded[0] - 1
        
        # distance transform to find boundaries in thresholded image
        distance = ndimage.distance_transform_edt(thresholded)
        
        if blobs is None:
            # default to finding peaks of distance transform if no blobs 
            # given, using an anisotropic footprint
            try:
                local_max = feature.peak_local_max(
                    distance, indices=False, footprint=np.ones((1, 3, 3)), 
                    labels=thresholded)
            except IndexError as e:
                print(e)
                raise e
            markers = measure.label(local_max)
        else:
            markers = _markers_from_blobs(thresholded, blobs)
        
        # watershed with slight increase in compactness to give basins with 
        # more regular, larger shape
        labels_ws = morphology.watershed(-distance, markers, compactness=0.1)
        
        # clean up segmentation
        labels_ws = _carve_segs(labels_ws, blobs)
        labels_ws = morphology.remove_small_objects(labels_ws, min_size=100)
        #print("num ws blobs: {}".format(len(np.unique(labels_ws)) - 1))
        labels_ws = labels_ws[None]
        labels.append(labels_ws)
    return labels_ws
