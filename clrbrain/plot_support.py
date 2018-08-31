#!/bin/bash
# Plot Support for Clrbrain
# Author: David Young, 2018
"""Shared plotting functions with the Clrbrain package.
"""

import numpy as np
from matplotlib.colors import (ListedColormap, LinearSegmentedColormap, NoNorm, 
                               Normalize)
import matplotlib.backend_bases as backend_bases

from clrbrain import config
from clrbrain import detector
from clrbrain import lib_clrbrain
from clrbrain import plot_3d

CMAP_GRBK = LinearSegmentedColormap.from_list(
    config.CMAP_GRBK_NAME, ["black", "green"])
CMAP_RDBK = LinearSegmentedColormap.from_list(
    config.CMAP_RDBK_NAME, ["black", "red"])

def imshow_multichannel(ax, img2d, channel, colormaps, aspect, alpha, 
                        vmin=None, vmax=None, origin=None, interpolation=None, 
                        norms=None):
    """Show multichannel 2D image with channels overlaid over one another.
    
    Args:
        ax: Axes plot.
        img2d: 2D image either as 2D (y, x) or 3D (y, x, channel) array.
        channel: Channel to display; if None, all channels will be shown.
        colormaps: List of colormaps corresponding to each channel. Colormaps 
            can be the names of specific maps in :mod:``config``.
        aspect: Aspect ratio.
        alpha: Default alpha transparency level.
        vim: Imshow vmin level; defaults to None.
        vmax: Imshow vmax level; defaults to None.
        origin: Image origin; defaults to None.
        interpolation: Type of interpolation; defaults to None.
        norms: List of normalizations, which should correspond to ``colormaps``.
    """
    # assume that 3D array has a channel dimension
    multichannel, channels = plot_3d.setup_channels(img2d, channel, 2)
    img = []
    i = 0
    vmin_plane = None
    vmax_plane = None
    for chl in channels:
        img2d_show = img2d[..., chl] if multichannel else img2d
        if i == 1:
            # after the 1st channel, all subsequent channels are transluscent
            alpha *= 0.3
        cmap = colormaps[chl]
        norm = None if norms is None else norms[chl]
        # check for custom colormaps
        if cmap == config.CMAP_GRBK_NAME:
            cmap = CMAP_GRBK
        elif cmap == config.CMAP_RDBK_NAME:
            cmap = CMAP_RDBK
        if vmin is not None:
            vmin_plane = vmin[chl]
        if vmax is not None:
            vmax_plane = vmax[chl]
        #print("vmin: {}, vmax: {}".format(vmin_plane, vmax_plane))
        img_chl = ax.imshow(
            img2d_show, cmap=cmap, norm=norm, aspect=aspect, alpha=alpha, 
            vmin=vmin_plane, vmax=vmax_plane, origin=origin, 
            interpolation=interpolation)
        img.append(img_chl)
        i += 1
    return img

def max_plane(img3d, plane):
    """Get the max plane for the given 3D image.
    
    Args:
        img3d: Image array in (z, y, x) order.
        plane: Plane as a value from :attr:``config.PLANE``.
    
    Returns:
        Number of elements along ``plane``'s axis.
    """
    shape = img3d.shape
    if plane == config.PLANE[1]:
        return shape[1]
    elif plane == config.PLANE[2]:
        return shape[2]
    else:
        return shape[0]

def transpose_images(plane, arrs_3d=None, arrs_1d=None):
    origin = None
    aspect = None # aspect ratio
    
    def swap(indices):
        arrs_3d_swapped = None
        arrs_1d_swapped = None
        if arrs_3d is not None:
            arrs_3d_swapped = [np.swapaxes(arr, *indices) for arr in arrs_3d]
        if arrs_1d is not None:
            arrs_1d_swapped = [
                lib_clrbrain.swap_elements(np.copy(arr), *indices) 
                for arr in arrs_1d]
        return arrs_3d_swapped, arrs_1d_swapped
    
    if plane == config.PLANE[1]:
        # xz plane
        aspect = detector.resolutions[0, 0] / detector.resolutions[0, 2]
        origin = "lower"
        # make y the "z" axis
        arrs_3d, arrs_1d = swap((0, 1))
    elif plane == config.PLANE[2]:
        # yz plane
        aspect = detector.resolutions[0, 0] / detector.resolutions[0, 1]
        origin = "lower"
        # make x the "z" axis for stack of 2D plots, such as animations
        arrs_3d, arrs_1d = swap((0, 2))
        arrs_3d, arrs_1d = swap((1, 2))
    else:
        # defaults to "xy"
        aspect = detector.resolutions[0, 1] / detector.resolutions[0, 2]
    return arrs_3d, arrs_1d, aspect, origin

def get_labels_colormap(labels, seed=None, alpha=150, index_direct=True, 
                         multiplier=255, offset=0, background=None):
    '''Generate discrete colormap for labels, using 
    :func:``lib_clrbrain.discrete_colormap``.
    
    Args:
        labels: Labels of integers for which a distinct color should be 
            mapped to each unique label.
        seed: Seed for randomizer to allow consistent colormap between runs; 
            defaults to None.
        alpha: Transparency leve; defaults to 150 for semi-transparent.
        index_direct: True if the colormap will be indexed directly, which 
            assumes that the labels will serve as indexes to the colormap and 
            should span sequentially from 0, 1, 2, ...; defaults to True. 
            If False, a colormap will be generated for the full range of 
            integers between the lowest and highest label values, inclusive.
        multiplier: Multiplier for random values generated for RGB values; 
            defaults to 255.
        offset: Offset to generated random numbers; defaults to 0.
        background: Tuple of (backround_label, (R, G, B, A)), where 
            background_label is the label value specifying the background, 
            and RGBA value will replace the color corresponding to that label. 
            Defaults to None.
    
    Return:
        Tuple of ``cmap_labels``, the discrete colormap, and ``norm``, the 
        normalization object for use with the colormap.
    '''
        
    if index_direct:
        # colormap will be indexed directly by labels image, so num of colors 
        # equals num of labels
        num_colors = len(np.unique(labels))
        norm = NoNorm()
    else:
        # generate a color for each int from lowest to highest label, incl 
        # vals not present in labels, and normalize this range of labels to 
        # index these colors
        labels_max = np.amax(labels)
        labels_min = np.amin(labels)
        num_colors = labels_max - labels_min + 1 # since inclusive
        norm = Normalize(vmin=labels_min, vmax=labels_max)
    cmap_labels = lib_clrbrain.discrete_colormap(
        num_colors, alpha=alpha, prioritize_default=False, seed=seed, 
        multiplier=multiplier, offset=offset)
    if background is not None:
        # replace backgound label color with given color
        bkgdi = np.where(
            np.array(range(labels_min, labels_max + 1)) == background[0])
        if len(bkgdi) > 0 and bkgdi[0].size > 0:
            cmap_labels[bkgdi[0][0]] = background[1]
    # listed rather than linear cmap since num of colors should equal num 
    # of possible vals, without requiring interpolation
    cmap_labels = ListedColormap(cmap_labels / 255.0, "discrete_cmap")
    return cmap_labels, norm

def scroll_plane(event, z_overview, max_size, jump=None):
    """Scroll through overview images along their orthogonal axis.
    
    Args:
        event: Mouse or key event. For mouse events, scroll step sizes 
            will be used for movements. For key events, up/down arrows 
            will be used.
        max_size: Maximum number of planes.
        jump: Function to jump to a given plane; defaults to None.
    """
    step = 0
    if isinstance(event, backend_bases.MouseEvent):
        # scroll movements are scaled from 0 for each event
        step += int(event.step) # decimal point num on some platforms
    elif isinstance(event, backend_bases.KeyEvent):
        # finer-grained movements through keyboard controls since the 
        # finest scroll movements may be > 1
        if event.key == "up":
            step += 1
        elif event.key == "down":
            step -= 1
        elif jump is not None and event.key == "right":
            z = jump(event)
            if z: z_overview = z
    
    z_overview_new = z_overview + step
    #print("scroll step of {} to z {}".format(step, z_overview))
    if z_overview_new < 0:
        z_overview_new = 0
    elif z_overview_new >= max_size:
        z_overview_new = max_size - 1
    return z_overview_new

def hide_axes(ax):
    """Hides x- and y-axes.
    """
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)

def set_overview_title(ax, plane, z_overview, zoom=1, level=0, 
                        max_intens_proj=False):
    """Set the overview image title.
    
    Args:
        ax: Matplotlib axes on which to display the title.
        plane: Plane string.
        z_overview: Value along the axis corresponding to that plane.
        zoom: Amount of zoom for the overview image.
        level: Overview view image level, where 0 is unzoomed, 1 is the 
            next zoom, etc.
    """
    plane_axis = get_plane_axis(plane)
    if level == 0:
        if max_intens_proj:
            title = "Max Intensity Projection"
        else:
            # show the axis and axis value for unzoomed overview
            title = "{}={}".format(plane_axis, z_overview)
    else:
        # show zoom for subsequent overviews
        title = "{}x".format(int(zoom))
    ax.set_title(title)

def get_plane_axis(plane):
    """Gets the name of the plane corresponding to the given axis.
    
    Args:
        plane: An element of :attr:``config.PLANE``.
    
    Returns:
        The axis name orthogonal to :attr:``config.PLANE``.
    """
    plane_axis = "z"
    if plane == config.PLANE[1]:
        plane_axis = "y"
    elif plane == config.PLANE[2]:
        plane_axis = "x"
    return plane_axis

if __name__ == "__main__":
    print("Starting plot support")