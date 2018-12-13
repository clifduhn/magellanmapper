# 2D plots from stacks of imaging data
# Author: David Young, 2017, 2018
"""Plots 2D views through multiple levels of a 3D stack for
comparison with 3D visualization.

Attributes:
    colormap_2d: The Matplotlib colormap for 2D plots.
    verify: If true, verification mode is turned on, which for now
        simply turns on interior borders as the picker remains on
        by default.
    padding: Padding in pixels (x, y), or planes (z) in which to show
        extra segments.
"""

import os
import math
from time import time

import numpy as np
from matplotlib import pyplot as plt, cm
from matplotlib.collections import PatchCollection
import matplotlib.gridspec as gridspec
import matplotlib.patches as patches
import matplotlib.pylab as pylab
from matplotlib.widgets import Slider, Button
from matplotlib_scalebar.scalebar import ScaleBar
from matplotlib_scalebar.scalebar import SI_LENGTH
import pandas as pd
from skimage import exposure
from skimage import transform

from clrbrain import detector
from clrbrain import importer
from clrbrain import colormaps
from clrbrain import config
from clrbrain import lib_clrbrain
from clrbrain import plot_3d
from clrbrain import plot_support
from clrbrain import stats

colormap_2d = cm.inferno
#colormap_2d = cm.gray
verify = False
# TODO: may want to base on scaling factor instead
padding = (5, 5, 3) # human (x, y, z) order

SEG_LINEWIDTH = 1
ZOOM_COLS = 9
Z_LEVELS = ("bottom", "middle", "top")
CIRCLES = ("Circles", "Repeat circles", "No circles", "Full annotation")
_DOWNSAMPLE_THRESH = 1000

# need to store DraggableCircles objects to prevent premature garbage collection
_draggable_circles = []
_circle_last_picked = []
_CUT = "cut"
_COPY = "copy"

segs_color_dict = {
    -1: "none",
    0: "r",
    1: "g",
    2: "y"
}

truth_color_dict = {
    -1: None,
    0: "m",
    1: "b"
}

edgecolor_dict = {
    0: "w",
    1: "c",
    2: "y",
    3: "m",
    4: "g"
}

class DraggableCircle:
    def __init__(self, circle, segment, fn_update_seg, color="none"):
        self.circle = circle
        self.circle.set_picker(5)
        self.facecolori = -1
        for key, val in segs_color_dict.items():
            if val == color:
                self.facecolori = key
        self.press = None
        self.segment = segment
        self.fn_update_seg = fn_update_seg
    
    def connect(self):
        """Connect events to functions.
        """
        self.cidpress = self.circle.figure.canvas.mpl_connect(
            "button_press_event", self.on_press)
        self.cidrelease = self.circle.figure.canvas.mpl_connect(
            "button_release_event", self.on_release)
        self.cidmotion = self.circle.figure.canvas.mpl_connect(
            "motion_notify_event", self.on_motion)
        self.cidpick = self.circle.figure.canvas.mpl_connect(
            "pick_event", self.on_pick)
        #print("connected circle at {}".format(self.circle.center))
    
    def remove_self(self):
        self.disconnect()
        self.circle.remove()
    
    def on_press(self, event):
        """Initiate drag events with Shift- or Alt-click inside a circle.
        
        Shift-click to move a circle, and Alt-click to resize a circle's radius.
        """
        if (event.key != "shift" and event.key != "alt" 
            or event.inaxes != self.circle.axes):
            return
        contains, attrd = self.circle.contains(event)
        if not contains: return
        print("pressed on {}".format(self.circle.center))
        x0, y0 = self.circle.center
        self.press = x0, y0, event.xdata, event.ydata
        DraggableCircle.lock = self
        
        # draw everywhere except the circle itself, store the pixel buffer 
        # in background, and draw the circle
        canvas = self.circle.figure.canvas
        ax = self.circle.axes
        self.circle.set_animated(True)
        canvas.draw()
        self.background = canvas.copy_from_bbox(self.circle.axes.bbox)
        ax.draw_artist(self.circle)
        canvas.blit(ax.bbox)
    
    def on_motion(self, event):
        """Move the circle if the drag event has been initiated.
        """
        if self.press is None: return
        if event.inaxes != self.circle.axes: return
        x0, y0, xpress, ypress = self.press
        dx = None
        dy = None
        if event.key == "shift":
            dx = event.xdata - xpress
            dy = event.ydata - ypress
            self.circle.center = x0 + dx, y0 + dy
        elif event.key == "alt":
            dx = abs(event.xdata - x0)
            dy = abs(event.ydata - y0)
            self.circle.radius = max([dx, dy])
        print("initial position: {}, {}; change thus far: {}, {}"
              .format(x0, y0, dx, dy))

        # restore the saved background and redraw the circle at its new position
        canvas = self.circle.figure.canvas
        ax = self.circle.axes
        canvas.restore_region(self.background)
        ax.draw_artist(self.circle)
        canvas.blit(ax.bbox)
    
    def on_release(self, event):
        """Finalize the circle and segment's position after a drag event
        is completed with a button release.
        """
        if self.press is None: return
        print("released on {}".format(self.circle.center))
        print("segment moving from {}...".format(self.segment))
        seg_old = np.copy(self.segment)
        self.segment[1:3] += np.subtract(
            self.circle.center, self.press[0:2]).astype(np.int)[::-1]
        rad_sign = -1 if self.segment[3] < config.POS_THRESH else 1
        self.segment[3] = rad_sign * self.circle.radius
        print("...to {}".format(self.segment))
        self.fn_update_seg(self.segment, seg_old)
        self.press = None
        
        # turn off animation property, reset background
        DraggableCircle.lock = None
        self.circle.set_animated(False)
        self.background = None
        self.circle.figure.canvas.draw()
    
    def on_pick(self, event):
        """Select the verification flag with button press on a circle when 
        not dragging the circle.
        """
        if (event.mouseevent.key == "control" 
            or event.mouseevent.key == "shift" 
            or event.mouseevent.key == "alt" 
            or event.artist != self.circle):
            return
        #print("color: {}".format(self.facecolori))
        if event.mouseevent.key == "x":
            # "cut" segment
            _circle_last_picked.append((self, _CUT))
            self.remove_self()
            print("cut seg: {}".format(self.segment))
        elif event.mouseevent.key == "c":
            # "copy" segment
            _circle_last_picked.append((self, _COPY))
            print("copied seg: {}".format(self.segment))
        elif event.mouseevent.key == "d":
            # delete segment, which will be stored as cut segment to allow 
            # undoing the deletion by pasting
            _circle_last_picked.append((self, _CUT))
            self.remove_self()
            self.fn_update_seg(self.segment, remove=True)
            print("deleted seg: {}".format(self.segment))
        else:
            # change verification flag
            seg_old = np.copy(self.segment)
            # "r"-click to change flag in reverse order
            change = -1 if event.mouseevent.key == "r" else 1
            i = self.facecolori + change
            # wrap around keys if exceeding min/max
            if i > max(segs_color_dict.keys()):
                if self.segment[3] < config.POS_THRESH:
                    # user-added segments simply disappear when exceeding
                    _circle_last_picked.append((self, _CUT))
                    self.remove_self()
                i = -1
            elif i < min(segs_color_dict.keys()):
                i = max(segs_color_dict.keys())
            self.circle.set_facecolor(segs_color_dict[i])
            self.facecolori = i
            self.segment[4] = i
            self.fn_update_seg(self.segment, seg_old)
            print("picked segment: {}".format(self.segment))

    def disconnect(self):
        """Disconnect event listeners.
        """
        self.circle.figure.canvas.mpl_disconnect(self.cidpress)
        self.circle.figure.canvas.mpl_disconnect(self.cidrelease)
        self.circle.figure.canvas.mpl_disconnect(self.cidmotion)

def _get_radius(seg):
    """Gets the radius for a segments, defaulting to 5 if the segment's
    radius is close to 0.
    
    Args:
        seg: The segments, where seg[3] is the radius.
    
    Returns:
        The radius, defaulting to 0 if the given radius value is close 
        to 0 by numpy.allclose.
    """
    radius = seg[3]
    if radius < config.POS_THRESH:
        radius *= -1
    return radius

def _circle_collection(segments, edgecolor, facecolor, linewidth):
    """Draws a patch collection of circles for segments.
    
    Args:
        segments: Numpy array of segments, generally as an (n, 4)
            dimension array, where each segment is in (z, y, x, radius).
        edgecolor: Color of patch borders.
        facecolor: Color of patch interior.
        linewidth: Width of the border.
    
    Returns:
        The patch collection.
    """
    seg_patches = []
    for seg in segments:
        seg_patches.append(patches.Circle((seg[2], seg[1]), radius=_get_radius(seg)))
    collection = PatchCollection(seg_patches)
    collection.set_edgecolor(edgecolor)
    collection.set_facecolor(facecolor)
    collection.set_linewidth(linewidth)
    return collection

def _plot_circle(ax, segment, linewidth, linestyle, fn_update_seg, 
                 alpha=0.5):
    """Create and draw a DraggableCircle from the given segment.
    
    Args:
        ax: Matplotlib axes.
        segment: Numpy array of segments, generally as an (n, 4)
            dimension array, where each segment is in (z, y, x, radius).
        linewidth: Edge line width.
        linestyle: Edge line style.
        fn_update_seg: Function to call from DraggableCircle.
        alpha: Alpha transparency level; defaults to 0.5.
    
    Returns:
        The DraggableCircle object.
    """
    facecolor = segs_color_dict[detector.get_blob_confirmed(segment)]
    edgecolor = edgecolor_dict[detector.get_blob_channel(segment)]
    circle = patches.Circle(
        (segment[2], segment[1]), radius=_get_radius(segment), 
        edgecolor=edgecolor, facecolor=facecolor, linewidth=linewidth, 
        linestyle=linestyle, alpha=alpha)
    ax.add_patch(circle)
    #print("added circle: {}".format(circle))
    draggable_circle = DraggableCircle(
        circle, segment, fn_update_seg, facecolor)
    draggable_circle.connect()
    _draggable_circles.append(draggable_circle)
    return draggable_circle

def add_scale_bar(ax, downsample=None):
    """Adds a scale bar to the plot.
    
    Uses the x resolution value and assumes that it is in microns per pixel.
    
    Args:
        ax: The plot that will show the bar.
        downsample: Downsampling factor by which the resolution will be 
            multiplied; defaults to None.
    """
    res = detector.resolutions[0][2]
    if downsample:
        res *= downsample
    scale_bar = ScaleBar(res, u'\u00b5m', SI_LENGTH, 
                         box_alpha=0, color="w", location=3)
    ax.add_artist(scale_bar)

def show_subplot(fig, gs, row, col, image5d, channel, roi_size, offset, 
                 fn_update_seg, segs_in, segs_out, segs_cmap, alpha, 
                 z_relative, highlight=False, border=None, plane="xy", 
                 roi=None, labels=None, blobs_truth=None, circles=None, 
                 aspect=None, grid=False, cmap_labels=None):
    """Shows subplots of the region of interest.
    
    Args:
        fig: Matplotlib figure.
        gs: Gridspec layout.
        row: Row number of the subplot in the layout.
        col: Column number of the subplot in the layout.
        image5d: Full Numpy array of the image stack.
        channel: Channel of the image to display.
        roi_size: List of x,y,z dimensions of the ROI.
        offset: Tuple of x,y,z coordinates of the ROI.
        segs_in: Numpy array of segments within the ROI to display in the 
            subplot, which can be None. Segments are generally given as an 
            (n, 4) dimension array, where each segment is in (z, y, x, radius).
        segs_out: Subset of segments that are adjacent to rather than
            inside the ROI, which will be drawn in a different style. Can be 
            None.
        segs_cmap: Colormap for segments.
        alpha: Opacity level.
        z_relative: Index of the z-plane relative to the start of the ROI.
        highlight: If true, the plot will be highlighted; defaults 
            to False.
        border: Border dimensions in pixels given as (x, y, z); defaults
            to None.
        plane: The plane to show in each 2D plot, with "xy" to show the 
            XY plane (default) and "xz" to show XZ plane.
        roi: A denoised region of interest, to show in place of image5d for the
            zoomed images. Defaults to None, in which case image5d will be
            used instead.
        labels: Segmentation labels; defaults to None.
        blobs_truth: Truth blobs formatted similarly to ``segs_in``; defaults 
            to None; defaults to None.
        circles: Type of circles to display, which should be a value of 
            :const:``CIRCLES``; defaults to None.
        aspect: Image aspect; defauls to None.
        grid: True if a grid should be overlaid; defaults to False.
        cmap_labels: :class:``colormaps.DiscreteColormap`` for labels; 
            defaults to None.
    """
    ax = plt.subplot(gs[row, col])
    plot_support.hide_axes(ax)
    size = image5d.shape
    # swap columns if showing a different plane
    plane_axis = plot_support.get_plane_axis(plane)
    image5d_shape_offset = 1 if image5d.ndim >= 4 else 0
    if plane == config.PLANE[1]:
        # "xz" planes
        size = lib_clrbrain.swap_elements(size, 0, 1, image5d_shape_offset)
    elif plane == config.PLANE[2]:
        # "yz" planes
        size = lib_clrbrain.swap_elements(size, 0, 2, image5d_shape_offset)
        size = lib_clrbrain.swap_elements(size, 0, 1, image5d_shape_offset)
    z = offset[2]
    ax.set_title("{}={}".format(plane_axis, z))
    if border is not None:
        # boundaries of border region, with xy point of corner in first 
        # elements and [width, height] in 2nd, allowing flipping for yz plane
        border_bounds = np.array(
            [border[0:2], 
            [roi_size[0] - 2 * border[0], roi_size[1] - 2 * border[1]]])
    if z < 0 or z >= size[image5d_shape_offset]:
        print("skipping z-plane {}".format(z))
        plt.imshow(np.zeros(roi_size[0:2]))
    else:
        # show the zoomed in 2D region
        
        # calculate the region depending on whether given ROI directly and 
        # remove time dimension since roi argument does not have it
        if roi is None:
            region = [offset[2], 
                      slice(offset[1], offset[1] + roi_size[1]), 
                      slice(offset[0], offset[0] + roi_size[0])]
            roi = image5d[0]
            #print("region: {}".format(region))
        else:
            region = [z_relative, slice(0, roi_size[1]), 
                      slice(0, roi_size[0])]
        # swap columns if showing a different plane
        if plane == config.PLANE[1]:
            region = lib_clrbrain.swap_elements(region, 0, 1)
        elif plane == config.PLANE[2]:
            region = lib_clrbrain.swap_elements(region, 0, 2)
            region = lib_clrbrain.swap_elements(region, 0, 1)
        # get the zoomed region
        if roi.ndim >= 4:
            roi = roi[tuple(region + [slice(None)])]
        else:
            roi = roi[tuple(region)]
        #print("roi shape: {}".format(roi.shape))
        
        if highlight:
            # highlight borders of z plane at bottom of ROI
            for spine in ax.spines.values():
                spine.set_edgecolor("yellow")
        if grid:
            # draw grid lines by directly editing copy of image
            grid_intervals = (roi_size[0] // 4, roi_size[1] // 4)
            roi = np.copy(roi)
            roi[::grid_intervals[0], :] = roi[::grid_intervals[0], :] / 2
            roi[:, ::grid_intervals[1]] = roi[:, ::grid_intervals[1]] / 2
        
        # show the ROI, which is now a 2D zoomed image
        cmaps = config.process_settings["channel_colors"]
        plot_support.imshow_multichannel(
            ax, roi, channel, cmaps, aspect, alpha)#, 0.0, config.vmax_overview)
        #print("roi shape: {} for z_relative: {}".format(roi.shape, z_relative))
        
        # show labels if provided and within ROI
        if labels is not None:
            for i in range(len(labels)):
                label = labels[i]
                if z_relative >= 0 and z_relative < label.shape[0]:
                    '''
                    try:
                        ax.contour(label[z_relative], colors="C{}".format(i))\
                        pass
                    except ValueError as e:
                        print(e)
                        print("could not show label:\n{}".format(label[z_relative]))
                    '''
                    ax.imshow(label[z_relative], cmap=cmap_labels, norm=cmap_labels.norm)
                    #ax.imshow(label[z_relative]) # showing only threshold
        
        if ((segs_in is not None or segs_out is not None) 
            and not circles == CIRCLES[2].lower()):
            segs_in = np.copy(segs_in)
            if circles is None or circles == CIRCLES[0].lower():
                # show circles at detection point only mode: 
                # zero radius of all segments outside of current z to preserve 
                # the order of segments for the corresponding colormap order 
                # while hiding outside segments
                segs_in[segs_in[:, 0] != z_relative, 3] = 0
            
            if segs_in is not None and segs_cmap is not None:
                if circles in (CIRCLES[1].lower(), CIRCLES[3].lower()):
                    # repeat circles and full annotation: 
                    # show segments from all z's as circles with colored 
                    # outlines, gradually decreasing in size when moving away 
                    # from the blob's central z-plane
                    z_diff = np.abs(np.subtract(segs_in[:, 0], z_relative))
                    r_orig = np.abs(np.copy(segs_in[:, 3]))
                    segs_in[:, 3] = np.subtract(
                        r_orig, np.divide(z_diff, 3))
                    # make circles below 90% of their original radius 
                    # invisible but not removed to preserve their corresponding 
                    # colormap index
                    segs_in[np.less(
                        segs_in[:, 3], np.multiply(r_orig, 0.9)), 3] = 0
                # show colored, non-pickable circles
                segs_color = segs_in
                if circles == CIRCLES[3].lower():
                    # zero out circles from other z's in full annotation mode 
                    # to minimize crowding and highlight center circle
                    segs_color = np.copy(segs_in)
                    segs_color[segs_color[:, 0] != z_relative, 3] = 0
                collection = _circle_collection(
                    segs_color, segs_cmap.astype(float) / 255.0, "none", 
                    SEG_LINEWIDTH)
                ax.add_collection(collection)
            
            # segments outside the ROI shown in black dotted line only for 
            # their corresponding z
            segs_out_z = None
            if segs_out is not None:
                segs_out_z = segs_out[segs_out[:, 0] == z_relative]
                collection_adj = _circle_collection(
                    segs_out_z, "k", "none", SEG_LINEWIDTH)
                collection_adj.set_linestyle("--")
                ax.add_collection(collection_adj)
            
            if z_relative >= 0 and z_relative < roi_size[2]:
                # for planes within ROI, overlay segments with dotted line 
                # patch and make pickable for verifying the segment
                segments_z = segs_in[segs_in[:, 3] > 0] # full annotation
                if circles == CIRCLES[3].lower():
                    # when showing full annotation, show all segments in the 
                    # ROI with adjusted radii unless radius is <= 0
                    for i in range(len(segments_z)):
                        seg = segments_z[i]
                        if seg[0] != z_relative:
                            # add segments outside of plane to Visualizer table 
                            # since they have been added to the plane, 
                            # adjusting rel and abs z coords to the given plane
                            z_diff = z_relative - seg[0]
                            seg[0] = z_relative
                            detector.shift_blob_abs_coords(
                                segments_z[i], (z_diff, 0, 0))
                            segments_z[i] = fn_update_seg(seg)
                else:
                    # apply only to segments in their current z
                    segments_z = segs_in[segs_in[:, 0] == z_relative]
                    if segs_out_z is not None:
                        segs_out_z_confirmed = segs_out_z[
                            detector.get_blob_confirmed(segs_out_z) == 1]
                        if len(segs_out_z_confirmed) > 0:
                            # include confirmed blobs 
                            segments_z = np.concatenate(
                                (segments_z, segs_out_z_confirmed))
                            print("segs_out_z_confirmed:\n{}"
                                  .format(segs_out_z_confirmed))
                if segments_z is not None:
                    # show pickable circles
                    for seg in segments_z:
                        _plot_circle(
                            ax, seg, SEG_LINEWIDTH, ":", fn_update_seg)
            
            # shows truth blobs as small, solid circles
            if blobs_truth is not None:
                for blob in blobs_truth:
                    ax.add_patch(patches.Circle(
                        (blob[2], blob[1]), radius=3, 
                        facecolor=truth_color_dict[blob[5]], alpha=1))
        
        # adds a simple border to highlight the border of the ROI
        if border is not None:
            #print("border: {}, roi_size: {}".format(border, roi_size))
            ax.add_patch(patches.Rectangle(border_bounds[0], 
                                           border_bounds[1, 0], 
                                           border_bounds[1, 1], 
                                           fill=False, edgecolor="yellow",
                                           linestyle="dashed", 
                                           linewidth=SEG_LINEWIDTH))
        
    return ax

def plot_roi(roi, segments, channel, show=True, title=""):
    """Plot ROI as sequence of z-planes containing only the ROI itself.
    
    Args:
        roi: The ROI image as a 3D array in (z, y, x) order.
        segments: Numpy array of segments to display in the subplot, which 
            can be None. Segments are generally given as an (n, 4)
            dimension array, where each segment is in (z, y, x, radius).
            All segments are assumed to be within the ROI for display.
        channel: Channel of the image to display.
        show: True if the plot should be displayed to screen; defaults 
            to True.
        title: String used as basename of output file. Defaults to "" 
            and only used if :attr:``config.savefig`` is set to a file 
            extension.
    """
    fig = plt.figure()
    #fig.suptitle(title)
    # total number of z-planes
    z_planes = roi.shape[0]
    # wrap plots after reaching max, but tolerates additional column
    # if it will fit all the remainder plots from the last row
    zoom_plot_rows = math.ceil(z_planes / ZOOM_COLS)
    col_remainder = z_planes % ZOOM_COLS
    zoom_plot_cols = ZOOM_COLS
    if col_remainder > 0 and col_remainder < zoom_plot_rows:
        zoom_plot_cols += 1
        zoom_plot_rows = math.ceil(z_planes / zoom_plot_cols)
        col_remainder = z_planes % zoom_plot_cols
    roi_size = roi.shape[::-1]
    zoom_offset = [0, 0, 0]
    gs = gridspec.GridSpec(
        zoom_plot_rows, zoom_plot_cols, wspace=0.1, hspace=0.1)
    image5d = importer.roi_to_image5d(roi)
    
    # plot the fully zoomed plots
    for i in range(zoom_plot_rows):
        # adjust columns for last row to number of plots remaining
        cols = zoom_plot_cols
        if i == zoom_plot_rows - 1 and col_remainder > 0:
            cols = col_remainder
        # show zoomed in plots and highlight one at offset z
        for j in range(cols):
            # z relative to the start of the ROI, since segs are relative to ROI
            z = i * zoom_plot_cols + j
            zoom_offset[2] = z
            
            # shows the zoomed subplot with scale bar for the current z-plane 
            # with all segments
            ax_z = show_subplot(
                fig, gs, i, j, image5d, channel, roi_size, zoom_offset, None,
                segments, None, None, 1.0, z, circles=CIRCLES[0], 
                roi=roi)
            if i == 0 and j == 0:
                add_scale_bar(ax_z)
    gs.tight_layout(fig, pad=0.5)
    if show:
        plt.show()
    if config.savefig is not None:
        plt.savefig(title + "." + config.savefig)

def plot_2d_stack(fn_update_seg, title, filename, image5d, channel, roi_size, 
                  offset, segments, mask_in, segs_cmap, fn_close_listener, 
                  border=None, plane="xy", padding_stack=None,
                  zoom_levels=2, single_zoom_row=False, z_level=Z_LEVELS[0], 
                  roi=None, labels=None, blobs_truth=None, circles=None, 
                  mlab_screenshot=None, grid=False, zoom_cols=ZOOM_COLS, 
                  img_region=None, max_intens_proj=False):
    """Shows a figure of 2D plots to compare with the 3D plot.
    
    Args:
        title: Figure title.
        image5d: Full Numpy array of the image stack.
        channel: Channel of the image to display.
        roi_size: List of x,y,z dimensions of the ROI.
        offset: Tuple of x,y,z coordinates of the ROI.
        segments: Numpy array of segments to display in the subplot, which 
            can be None. Segments are generally given as an (n, 4)
            dimension array, where each segment is in (z, y, x, radius), and 
            coordinates are relative to ``offset``.
            This array can include adjacent segments as well.
        mask_in: Boolean mask of ``segments`` within the ROI.
        segs_cmap: Colormap for segments inside the ROI.
        fn_close_listener: Handle figure close events.
        border: Border dimensions in pixels given as (x, y, z); defaults
            to None.
        plane: The plane to show in each 2D plot, with "xy" to show the 
            XY plane (default) and "xz" to show XZ plane.
        padding_stack: The amount of padding in pixels, defaulting to the 
            padding attribute.
        zoom_levels: Number of zoom levels to include, with n - 1 levels
            included at the overview level, and the last one viewed
            as the series of ROI-sized plots; defaults to 2.
        single_zoom_row: True if the ROI-sized zoomed plots should be
            displayed on a single row; defaults to False.
        z_level: Position of the z-plane shown in the overview plots,
            based on the Z_LEVELS attribute constant; defaults to 
            Z_LEVELS[0].
        roi: A denoised region of interest for display in fully zoomed plots. 
            Defaults to None, in which case image5d will be used instead.
        zoom_cols: Number of columns per row to reserve for zoomed plots; 
            defaults to :attr:``ZOOM_COLS``.
        img_region: 3D boolean or binary array corresponding to a scaled 
            version of ``image5d`` with the selected region labeled as True 
            or 1. ``config.labels_scaling`` will be used to scale up this 
            region to overlay on overview images. Defaults to None, in which 
            case the region will be ignored.
        max_intens_proj: True to show overview images as local max intensity 
            projections through the ROI. Defaults to Faslse.
    """
    time_start = time()
    
    fig = plt.figure()
    # black text with transluscent background the color of the figure
    # background in case the title is a 2D plot
    fig.suptitle(title, color="black", 
                 bbox=dict(facecolor=fig.get_facecolor(), edgecolor="none", 
                           alpha=0.5))
    if circles is not None:
        circles = circles.lower()
    
    # adjust array order based on which plane to show
    border_full = np.copy(border)
    border[2] = 0
    scaling = None
    if config.labels_scaling is not None:
        # check for None since np.copy of None is not None
        scaling = np.copy(config.labels_scaling)
    if plane == config.PLANE[1]:
        # "xz" planes; flip y-z to give y-planes instead of z
        roi_size = lib_clrbrain.swap_elements(roi_size, 1, 2)
        offset = lib_clrbrain.swap_elements(offset, 1, 2)
        border = lib_clrbrain.swap_elements(border, 1, 2)
        border_full = lib_clrbrain.swap_elements(border_full, 1, 2)
        if segments is not None and len(segments) > 0:
            segments[:, [0, 1]] = segments[:, [1, 0]]
        if scaling is not None:
            scaling = lib_clrbrain.swap_elements(scaling, 1, 2)
    elif plane == config.PLANE[2]:
        # "yz" planes; roll backward to flip x-z and x-y
        roi_size = lib_clrbrain.roll_elements(roi_size, -1)
        offset = lib_clrbrain.roll_elements(offset, -1)
        border = lib_clrbrain.roll_elements(border, -1)
        border_full = lib_clrbrain.roll_elements(border_full, -1)
        print("orig segments:\n{}".format(segments))
        if segments is not None and len(segments) > 0:
            # roll forward since segments in zyx order
            segments[:, [0, 2]] = segments[:, [2, 0]]
            segments[:, [1, 2]] = segments[:, [2, 1]]
            print("rolled segments:\n{}".format(segments))
        if scaling is not None:
            scaling = lib_clrbrain.roll_elements(scaling, -1)
    print("2D border: {}".format(border))
    
    # mark z-planes to show
    z_start = offset[2]
    z_planes = roi_size[2]
    if padding_stack is None:
        padding_stack = padding
    z_planes_padding = padding_stack[2] # additional z's above/below
    print("padding: {}, savefig: {}".format(padding, config.savefig))
    z_planes = z_planes + z_planes_padding * 2
    # position overview at bottom (default), middle, or top of stack
    z_overview = z_start # abs positioning
    if z_level == Z_LEVELS[1]:
        z_overview = (2 * z_start + z_planes) // 2
    elif z_level == Z_LEVELS[2]:
        z_overview = z_start + z_planes
    print("z_overview: {}".format(z_overview))
    max_size = plot_support.max_plane(image5d[0], plane)
    
    def prep_overview():
        """Prep overview image planes based on chosen orientation.
        """
        # main overview image
        z_range = z_overview
        if max_intens_proj:
            # max intensity projection (MIP) is local, through the entire ROI 
            # and thus not changing with scrolling
            z_range = np.arange(z_start, z_start + roi_size[2])
        img2d, aspect, origin = extract_plane(
            image5d, z_range, plane, max_intens_proj)
        img_region_2d = None
        if img_region is not None:
            # extract correponding plane from scaled region image and 
            # convert it to an RGBA image, using region as alpha channel and 
            # inverting it opacify areas outside of selected region; if in 
            # MIP mode, will still only show lowest plane
            img, _, _ = extract_plane(
                img_region, int(scaling[0] * z_overview), plane)
            img_region_2d = np.ones(img.shape + (4,))
            img_region_2d[..., 3] = np.invert(img) * 0.5
        return img2d, aspect, origin, img_region_2d
    
    img2d, aspect, origin, img_region_2d = prep_overview()
    
    # plot layout depending on number of z-planes
    if single_zoom_row:
        # show all plots in single row
        zoom_plot_rows = 1
        col_remainder = 0
        zoom_plot_cols = z_planes
    else:
        # wrap plots after reaching max, but tolerates additional column
        # if it will fit all the remainder plots from the last row
        zoom_plot_rows = math.ceil(z_planes / zoom_cols)
        col_remainder = z_planes % zoom_cols
        zoom_plot_cols = zoom_cols
        if col_remainder > 0 and col_remainder < zoom_plot_rows:
            zoom_plot_cols += 1
            zoom_plot_rows = math.ceil(z_planes / zoom_plot_cols)
            col_remainder = z_planes % zoom_plot_cols
    # overview plots is 1 > levels, but last spot is taken by screenshot
    top_cols = zoom_levels
    height_ratios = (3, zoom_plot_rows)
    if mlab_screenshot is None:
        # remove column for screenshot
        top_cols -= 1
        if img2d.shape[1] > 2 * img2d.shape[0]:
            # for wide ROIs, prioritize the fully zoomed plots, especially 
            # if only one overview column
            height_ratios = (1, 1) if top_cols >= 2 else (1, 2)
    gs = gridspec.GridSpec(2, top_cols, wspace=0.7, hspace=0.4,
                           height_ratios=height_ratios)
    
    # overview subplotting
    ax_overviews = [] # overview axes
    ax_z_list = [] # zoom plot axes
    
    def show_overview(ax, img2d_ov, img_region_2d, level):
        """Show overview image with progressive zooming on the ROI for each 
        zoom level.
        
        Args:
            ax: Subplot axes.
            img2d_ov: Image in which to zoom.
            level: Zoom level, where 0 is the original image.
        
        Returns:
            The zoom amount as by which ``img2d_ov`` was divided.
        """
        patch_offset = offset[0:2]
        zoom = 1
        if level > 0:
            # move origin progressively closer with each zoom level
            zoom_mult = math.pow(level, 3)
            origin = np.floor(np.multiply(
                offset[0:2], zoom_levels + zoom_mult - 1) 
                / (zoom_levels + zoom_mult)).astype(int)
            zoom_shape = np.flipud(img2d_ov.shape[:2])
            # progressively decrease size, zooming in for each level
            zoom = zoom_mult + 3
            size = np.floor(zoom_shape / zoom).astype(int)
            end = np.add(origin, size)
            # keep the zoomed area within the full 2D image
            for j in range(len(origin)):
                if end[j] > zoom_shape[j]:
                    origin[j] -= end[j] - zoom_shape[j]
            # zoom and position ROI patch position
            img2d_ov = img2d_ov[origin[1]:end[1], origin[0]:end[0]]
            if img_region_2d is not None:
                origin_scaled = np.multiply(
                    origin, scaling[2:0:-1]).astype(np.int)
                end_scaled = np.multiply(end, scaling[2:0:-1]).astype(np.int)
                img_region_2d = img_region_2d[
                    origin_scaled[1]:end_scaled[1], 
                    origin_scaled[0]:end_scaled[0]]
            #print(img2d_ov_zoom.shape, origin, size)
            patch_offset = np.subtract(patch_offset, origin)
        # show the zoomed 2D image along with rectangle showing ROI, 
        # downsampling by using threshold as mask
        downsample = np.max(
            np.divide(img2d_ov.shape, _DOWNSAMPLE_THRESH)).astype(np.int)
        if downsample < 1: 
            downsample = 1
        min_show = config.near_min
        max_show = config.vmax_overview
        if np.prod(img2d_ov.shape[1:3]) < 2 * np.prod(roi_size[:2]):
            # remove normalization from overview image if close in size to 
            # zoomed plots to emphasize the raw image
            min_show = None
            max_show = None
        img = img2d_ov[::downsample, ::downsample]
        plot_support.imshow_multichannel(
            ax, img, channel, cmaps, aspect, 1, min_show, max_show)
        if img_region_2d is not None:
            # overlay image with selected region highlighted by opacifying 
            # all surrounding areas
            img = transform.resize(
                img_region_2d, img.shape, order=0, anti_aliasing=True, 
                mode="reflect")
            ax.imshow(img)
        ax.add_patch(patches.Rectangle(
            np.divide(patch_offset, downsample), 
            *np.divide(roi_size[0:2], downsample), 
            fill=False, edgecolor="yellow"))
        add_scale_bar(ax, downsample)
        plot_support.set_overview_title(
            ax, plane, z_overview, zoom, level, max_intens_proj)
        return zoom
    
    def jump(event):
        z_overview = None
        if event.inaxes in ax_z_list:
            # right-arrow to jump to z-plane of given zoom plot
            z_overview = (ax_z_list.index(event.inaxes) + z_start 
                          - z_planes_padding)
        return z_overview
    
    def scroll_overview(event):
        """Scroll through overview images along their orthogonal axis.
        
        Args:
            event: Mouse or key event. For mouse events, scroll step sizes 
                will be used for movements. For key events, up/down arrows 
                will be used.
        """
        # no scrolling if MIP since already showing full ROI
        if max_intens_proj:
            print("skipping overview scrolling while showing max intensity "
                  "projection")
            return
        nonlocal z_overview
        z_overview_new = plot_support.scroll_plane(
            event, z_overview, max_size, jump)
        if z_overview_new != z_overview:
            # move only if step registered and changing position
            z_overview = z_overview_new
            img2d, aspect, origin, img_region_2d = prep_overview()
            for level in range(zoom_levels - 1):
                ax = ax_overviews[level]
                ax.clear() # prevent performance degradation
                zoom = show_overview(ax, img2d, img_region_2d, level)
    
    # overview images taken from the bottom plane of the offset, with
    # progressively zoomed overview images if set for additional zoom levels
    overview_cols = zoom_plot_cols // zoom_levels
    cmaps = config.process_settings["channel_colors"]
    for level in range(zoom_levels - 1):
        ax = plt.subplot(gs[0, level])
        ax_overviews.append(ax)
        plot_support.hide_axes(ax)
        zoom = show_overview(ax, img2d, img_region_2d, level)
    fig.canvas.mpl_connect("scroll_event", scroll_overview)
    fig.canvas.mpl_connect("key_press_event", scroll_overview)
    
    # zoomed-in views of z-planes spanning from just below to just above ROI
    segs_in = None
    segs_out = None
    if (circles != CIRCLES[2].lower() and segments is not None 
        and len(segments) > 0):
        # separate segments inside from outside the ROI
        if mask_in is not None:
            segs_in = segments[mask_in]
            segs_out = segments[np.invert(mask_in)]
        # separate out truth blobs
        if segments.shape[1] >= 6:
            if blobs_truth is None:
                blobs_truth = segments[segments[:, 5] >= 0]
            print("blobs_truth:\n{}".format(blobs_truth))
            # non-truth blobs have truth flag unset (-1)
            if segs_in is not None:
                segs_in = segs_in[segs_in[:, 5] == -1]
            if segs_out is not None:
                segs_out = segs_out[segs_out[:, 5] == -1]
            #print("segs_in:\n{}".format(segs_in))
        
    # selected or newly added patches since difficult to get patch from 
    # collection,and they don't appear to be individually editable
    seg_patch_dict = {}
    
    # sub-gridspec for fully zoomed plots to allow flexible number of columns
    gs_zoomed = gridspec.GridSpecFromSubplotSpec(zoom_plot_rows, zoom_plot_cols, 
                                                 gs[1, :],
                                                 wspace=0.1, hspace=0.1)
    cmap_labels = None
    if labels is not None:
        # background partially transparent to show any mismatch
        cmap_labels = colormaps.get_labels_discrete_colormap(labels, 100)
    # plot the fully zoomed plots
    #zoom_plot_rows = 0 # TESTING: show no fully zoomed plots
    for i in range(zoom_plot_rows):
        # adjust columns for last row to number of plots remaining
        cols = zoom_plot_cols
        if i == zoom_plot_rows - 1 and col_remainder > 0:
            cols = col_remainder
        # show zoomed in plots and highlight one at offset z
        for j in range(cols):
            # z relative to the start of the ROI, since segs are relative to ROI
            z_relative = i * zoom_plot_cols + j - z_planes_padding
            # absolute z value, relative to start of image5d
            z = z_start + z_relative
            zoom_offset = (offset[0], offset[1], z)
            
            # fade z-planes outside of ROI and show only image5d
            if z < z_start or z >= z_start + roi_size[2]:
                alpha = 0.5
                roi_show = None
            else:
                alpha = 1
                roi_show = roi
            
            # collects truth blobs within the given z-plane
            blobs_truth_z = None
            if blobs_truth is not None:
                blobs_truth_z = blobs_truth[np.all([
                    blobs_truth[:, 0] == z_relative, 
                    blobs_truth[:, 4] > 0], axis=0)]
            #print("blobs_truth_z:\n{}".format(blobs_truth_z))
            
            # shows border outlining area that will be saved if in verify mode
            show_border = (verify and z_relative >= border[2] 
                           and z_relative < roi_size[2] - border[2])
            
            # shows the zoomed subplot with scale bar for the current z-plane
            ax_z = show_subplot(
                fig, gs_zoomed, i, j, image5d, channel, roi_size, zoom_offset, 
                fn_update_seg,
                segs_in, segs_out, segs_cmap, alpha, z_relative, 
                z == z_overview, border_full if show_border else None, plane, 
                roi_show, labels, blobs_truth_z, circles=circles, 
                aspect=aspect, grid=grid, cmap_labels=cmap_labels)
            if i == 0 and j == 0:
                add_scale_bar(ax_z)
            ax_z_list.append(ax_z)
    
    if not circles == CIRCLES[2].lower():
        # add points that were not segmented by ctrl-clicking on zoom plots 
        # as long as not in "no circles" mode
        def on_btn_release(event):
            ax = event.inaxes
            print("event key: {}".format(event.key))
            if event.key is None:
                # for some reason becomes none if previous event was 
                # ctrl combo and this event is control
                pass
            elif event.key == "control" or event.key.startswith("ctrl"):
                seg_channel = channel
                if channel is None:
                    # specify channel by key combos if displaying multiple 
                    # channels
                    if event.key.endswith("+1"):
                        # ctrl+1
                        seg_channel = 1
                try:
                    axi = ax_z_list.index(ax)
                    if (axi != -1 and axi >= z_planes_padding 
                        and axi < z_planes - z_planes_padding):
                        
                        seg = np.array([[axi - z_planes_padding, 
                                         event.ydata.astype(int), 
                                         event.xdata.astype(int), -5]])
                        seg = detector.format_blobs(seg, seg_channel)
                        detector.shift_blob_abs_coords(seg, offset[::-1])
                        detector.update_blob_confirmed(seg, 1)
                        seg = fn_update_seg(seg[0])
                        # adds a circle to denote the new segment
                        patch = _plot_circle(
                            ax, seg, SEG_LINEWIDTH, "-", fn_update_seg)
                except ValueError as e:
                    print(e)
                    print("not on a plot to select a point")
            elif event.key == "v":
                _circle_last_picked_len = len(_circle_last_picked)
                if _circle_last_picked_len < 1:
                    print("No previously picked circle to paste")
                    return
                moved_item = _circle_last_picked[_circle_last_picked_len - 1]
                circle, move_type = moved_item
                axi = ax_z_list.index(ax)
                dz = axi - z_planes_padding - circle.segment[0]
                seg_old = np.copy(circle.segment)
                seg_new = np.copy(circle.segment)
                seg_new[0] += dz
                if move_type == _CUT:
                    print("Pasting a cut segment")
                    _draggable_circles.remove(circle)
                    _circle_last_picked.remove(moved_item)
                    seg_new = fn_update_seg(seg_new, seg_old)
                else:
                    print("Pasting a copied in segment")
                    detector.shift_blob_abs_coords(seg_new, (dz, 0, 0))
                    seg_new = fn_update_seg(seg_new)
                _plot_circle(
                    ax, seg_new, SEG_LINEWIDTH, ":", fn_update_seg)
           
        fig.canvas.mpl_connect("button_release_event", on_btn_release)
        # reset circles window flag
        fig.canvas.mpl_connect("close_event", fn_close_listener)
    
    # show 3D screenshot if available
    if mlab_screenshot is not None:
        img3d = mlab_screenshot
        ax = plt.subplot(gs[0, zoom_levels - 1])
        # auto to adjust size with less overlap
        ax.imshow(img3d)
        ax.set_aspect(img3d.shape[1] / img3d.shape[0])
        plot_support.hide_axes(ax)
    gs.tight_layout(fig, pad=0.5)
    #gs_zoomed.tight_layout(fig, pad=0.5)
    plt.ion()
    plt.show()
    #fig.set_size_inches(*(fig.get_size_inches() * 1.5), True)
    if config.savefig is not None:
        name = "{}_offset{}x{}.{}".format(
            os.path.basename(filename), offset, tuple(roi_size), 
            config.savefig).replace(" ", "")
        print("saving figure as {}".format(name))
        plt.savefig(name)
    print("2D plot time: {}".format(time() - time_start))
    
def extract_plane(image5d, plane_n, plane=None, max_intens_proj=False):
    """Extract a 2D plane or stack of planes.
    
    Args:
        image5d: The full image stack.
        plane_n: Slice of planes to extract, which can be a single index 
            or multiple indices such as would be used for an animation.
        plane: Type of plane to extract, which should be one of 
            :attribute:`config.PLANES`.
        max_intens_projection: True to show a max intensity projection, which 
            assumes that plane_n is an array of multiple, typically 
            contiguous planes along which the max intensity pixel will 
            be taken. Defaults to False.
    
    Returns:
        Tuple of an array of the image, which is 2D if ``plane_n`` is a 
        scalar or ``max_intens_projection`` is True, or 3D otherwise; 
        the aspect ratio; and the origin value.
    """
    origin = None
    aspect = None # aspect ratio
    img3d = None
    if image5d.ndim >= 4:
        img3d = image5d[0]
    else:
        img3d = image5d[:]
    arrs_3d, _, aspect, origin = plot_support.transpose_images(plane, [img3d])
    img3d = arrs_3d[0]
    img2d = img3d[plane_n]
    if max_intens_proj:
        # max intensity projection assumes axis 0 is the "z" axis
        img2d = np.amax(img2d, axis=0)
    #print("aspect: {}, origin: {}".format(aspect, origin))
    return img2d, aspect, origin

def cycle_colors(i):
    num_colors = len(config.colors)
    cycle = i // num_colors
    colori = i % num_colors
    color = config.colors[colori]
    '''
    print("num_colors: {}, cycle: {}, colori: {}, color: {}"
          .format(num_colors, cycle, colori, color))
    '''
    upper = 255
    if cycle > 0:
        color = np.copy(color)
        color[0] = color[0] + cycle * 5
        if color[0] > upper:
            color[0] -= upper * (color[0] // upper)
    return np.divide(color, upper)

def plot_roc(stats_dict, name):
    """Plot ROC curve.
    
    Args:
        stats_dict: Dictionary of statistics to plot as given by 
            :func:``mlearn.parse_grid_stats``.
        name: String to display as title.
    """
    fig = plt.figure()
    posi = 1 # position of legend
    for group, iterable_dicts in stats_dict.items():
        lines = []
        colori = 0
        for key, value in iterable_dicts.items():
            fdr = value[0]
            sens = value[1]
            params = value[2]
            line, = plt.plot(
                fdr, sens, label=key, lw=2, color=cycle_colors(colori), 
                linestyle="", marker=".")
            lines.append(line)
            colori += 1
            for i, n in enumerate(params):
                annotation = n
                if isinstance(n, float):
                    # limit max decimal points while avoiding trailing zeros
                    annotation = "{:.3g}".format(n)
                plt.annotate(annotation, (fdr[i], sens[i]))
        # iterated legend position to avoid overlap from multiple legends
        legend = plt.legend(
            handles=lines, loc=posi, title=group, fancybox=True, 
            framealpha=0.5)
        plt.gca().add_artist(legend)
        posi += 1
    plt.plot([0, 1], [0, 1], color="navy", lw=2, linestyle="--")
    plt.xlim([0.0, 1.2])
    plt.ylim([0.0, 1.0])
    plt.xlabel("False Discovery Rate")
    plt.ylabel("Sensitivity")
    plt.title("ROC for {}".format(name))
    plt.show()

def _show_overlay(ax, img, plane_i, cmap, out_plane, aspect=1.0, alpha=1.0, 
                  title=None):
    """Shows an image for overlays in the orthogonal plane specified by 
    :attribute:`plane`.
    
    Args:
        ax: Subplot axes.
        img: 3D image.
        plane_i: Plane index of `img` to show.
        cmap: Name of colormap.
        aspect: Aspect ratio; defaults to 1.0.
        alpha: Alpha level; defaults to 1.0.
        title: Subplot title; defaults to None, in which case no title will 
            be shown.
    """
    if out_plane == config.PLANE[1]:
        # xz plane
        img_2d = img[:, plane_i]
        img_2d = np.flipud(img_2d)
    elif out_plane == config.PLANE[2]:
        # yz plane, which requires a flip when original orientation is 
        # horizontal section
        # TODO: generalize to other original orientations
        img_2d = img[:, :, plane_i]
        #img_2d = np.swapaxes(img_2d, 1, 0)
        #aspect = 1 / aspect
        img_2d = np.flipud(img_2d)
    else:
        # xy plane (default)
        img_2d = img[plane_i]
    ax.imshow(img_2d, cmap=cmap, aspect=aspect, alpha=alpha)
    plot_support.hide_axes(ax)
    if title is not None:
        ax.set_title(title)

def plot_overlays(imgs, z, cmaps, title=None, aspect=1.0):
    """Plot images in a single row, with the final subplot showing an 
    overlay of all images.
    
    Args:
        imgs: List of 3D images to show.
        z: Z-plane to view for all images.
        cmaps: List of colormap names, which should be be the same length as 
            `imgs`, with the colormap applied to the corresponding image.
        title: Figure title; if None, will be given default title.
        aspect: Aspect ratio, which will be applied to all images; 
           defaults to 1.0.
    """
    # TODO: deprecated
    fig = plt.figure()
    fig.suptitle(title)
    imgs_len = len(imgs)
    gs = gridspec.GridSpec(1, imgs_len + 1)
    for i in range(imgs_len):
        print("showing img {}".format(i))
        _show_overlay(plt.subplot(gs[0, i]), imgs[i], z, cmaps[i], aspect)
    ax = plt.subplot(gs[0, imgs_len])
    for i in range(imgs_len):
        _show_overlay(ax, imgs[i], z, cmaps[i], aspect, alpha=0.5)
    if title is None:
        title = "Image overlays"
    gs.tight_layout(fig)
    plt.show()

def plot_overlays_reg(exp, atlas, atlas_reg, labels_reg, cmap_exp, 
                      cmap_atlas, cmap_labels, translation=None, title=None, 
                      out_plane=None, show=True):
    """Plot overlays of registered 3D images, showing overlap of atlas and 
    experimental image planes.
    
    Shows the figure on screen. If :attr:``config.savefig`` is set, 
    the figure will be saved to file with the extensive given by savefig.
    
    Args:
        exp: Experimental image.
        atlas: Atlas image, unregistered.
        atlas_reg: Atlas image, after registration.
        labels_reg: Atlas labels image, also registered.
        cmap_exp: Colormap for the experimental image.
        cmap_atlas: Colormap for the atlas.
        cmap_labels: Colormap for the labels.
        translation: Translation in (z, y, x) order for consistency with 
            operations on Numpy rather than SimpleITK images here; defaults 
            to None, in which case the chosen plane index for the 
            unregistered atlast will be the same fraction of its size as for 
            the registered image.
        title: Figure title; if None, will be given default title.
        out_plane: Output planar orientation.
        show: True if the plot should be displayed on screen; defaults to True.
    """
    fig = plt.figure()
    # give extra space to the first row since the atlas is often larger
    gs = gridspec.GridSpec(2, 3, height_ratios=[3, 2])
    resolution = detector.resolutions[0]
    #size_ratio = np.divide(atlas_reg.shape, exp.shape)
    aspect = 1.0
    z = 0
    atlas_z = 0
    plane_frac = 2#5 / 2
    if out_plane is None:
        out_plane = config.plane
    if out_plane == config.PLANE[1]:
        # xz plane
        aspect = resolution[0] / resolution[2]
        z = exp.shape[1] // plane_frac
        if translation is None:
            atlas_z = atlas.shape[1] // plane_frac
        else:
            atlas_z = int(z - translation[1])
    elif out_plane == config.PLANE[2]:
        # yz plane
        aspect = resolution[0] / resolution[1]
        z = exp.shape[2] // plane_frac
        if translation is None:
            atlas_z = atlas.shape[2] // plane_frac
        else:
            # TODO: not sure why needs to be addition here
            atlas_z = int(z + translation[2])
    else:
        # xy plane (default)
        aspect = resolution[1] / resolution[2]
        z = exp.shape[0] // plane_frac
        if translation is None:
            atlas_z = atlas.shape[0] // plane_frac
        else:
            atlas_z = int(z - translation[0])
    print("z: {}, atlas_z: {}, aspect: {}".format(z, atlas_z, aspect))
    
    # invert any neg values (one hemisphere) to minimize range and match other
    # hemisphere
    labels_reg[labels_reg < 0] = np.multiply(labels_reg[labels_reg < 0], -1)
    vmin, vmax = np.percentile(labels_reg, (5, 95))
    print("vmin: {}, vmax: {}".format(vmin, vmax))
    labels_reg = exposure.rescale_intensity(labels_reg, in_range=(vmin, vmax))
    '''
    labels_reg = labels_reg.astype(np.float)
    lib_clrbrain.normalize(labels_reg, 1, 100, background=15000)
    labels_reg = labels_reg.astype(np.int)
    print(labels_reg[290:300, 20, 190:200])
    '''
    
    # experimental image and atlas
    _show_overlay(plt.subplot(gs[0, 0]), exp, z, cmap_exp, out_plane, aspect, 
                              title="Experiment")
    _show_overlay(plt.subplot(gs[0, 1]), atlas, atlas_z, cmap_atlas, out_plane, 
                  alpha=0.5, title="Atlas")
    
    # atlas overlaid onto experiment
    ax = plt.subplot(gs[0, 2])
    _show_overlay(ax, exp, z, cmap_exp, out_plane, aspect, title="Registered")
    _show_overlay(ax, atlas_reg, z, cmap_atlas, out_plane, aspect, 0.5)
    
    # labels overlaid onto atlas
    ax = plt.subplot(gs[1, 0])
    _show_overlay(ax, atlas_reg, z, cmap_atlas, out_plane, aspect, title="Labeled atlas")
    _show_overlay(ax, labels_reg, z, cmap_labels, out_plane, aspect, 0.5)
    
    # labels overlaid onto exp
    ax = plt.subplot(gs[1, 1])
    _show_overlay(ax, exp, z, cmap_exp, out_plane, aspect, title="Labeled experiment")
    _show_overlay(ax, labels_reg, z, cmap_labels, out_plane, aspect, 0.5)
    
    # all overlaid
    ax = plt.subplot(gs[1, 2])
    _show_overlay(ax, exp, z, cmap_exp, out_plane, aspect, title="All overlaid")
    _show_overlay(ax, atlas_reg, z, cmap_atlas, out_plane, aspect, 0.5)
    _show_overlay(ax, labels_reg, z, cmap_labels, out_plane, aspect, 0.3)
    
    if title is None:
        title = "Image Overlays"
    fig.suptitle(title)
    gs.tight_layout(fig)
    if config.savefig is not None:
        plt.savefig(title + "." + config.savefig)
    if show:
        plt.show()

def _bar_plots(ax, lists, errs, list_names, x_labels, colors, y_label, 
               title, padding=0.2):
    """Generate grouped bar plots from lists, where corresponding elements 
    in the lists are grouped together.
    
    Data is given as a list of sublists. Each sublist contains a "set" of 
    values, with one value per "group." The number of groups is thus the 
    number of values per sublist, and the number of bars per group is 
    the number of sublists.
    
    Typically each sublist will represents an experimental set, such 
    as WT or het. Corresponding elements in each set are grouped together 
    to compare sets, such as WT vs het at time point 0. Bars groups where 
    all values would be below :attr:``config.POS_THRESH`` are not plotted.
    
    Args:
        ax: Axes.
        lists: Tuple of mean lists to display, with each list getting a 
            separate set of bar plots with a legend entry. All lists should 
            be the same size as one another. The number of lists should equal 
            the number of legend groups, and the number of entries in each list 
            should equal the number of bar groups.
        errs: Tuple of variance lists (eg standard deviation or error) to 
            display, with each list getting a separate
            set of bar plots. All lists should be the same size as one 
            another and each list in ``lists``.
        list_names: List of names of each list, where the list size should 
            be the same size as the length of ``lists``. If None, legend will 
            not be displayed.
        x_labels: List of labels for each bar group, where the list size 
            should be equal to the size of each list in ``lists``.
        y_label: Y-axis label.
        title: Graph title.
        padding: Fraction of the border space between each bar group 
            that should be left unoccupied by bars. Defaults to 0.8.
    """
    bars = []
    if len(lists) < 1: return
    
    # convert lists to Numpy arrays to allow fancy indexing
    lists = np.array(lists)
    if errs: errs = np.array(errs)
    x_labels = np.array(x_labels)
    #print("lists: {}".format(lists))
    
    # skip bar groups where all bars would be ~0; 
    # TODO: allow this threshold to be ignored
    mask = np.all(lists > config.POS_THRESH, axis=0)
    #print("mask: {}".format(mask))
    if np.all(mask):
        print("skip none")
    else:
        print("skipping {}".format(x_labels[~mask]))
        x_labels = x_labels[mask]
        lists = lists[:, mask]
        # len(errs) may be > 0 when errs.size == 0
        if errs is not None and errs.size > 0:
            errs = errs[:, mask]
    num_groups = len(lists[0])
    num_sets = len(lists) # num of bars per group
    indices = np.arange(num_groups)
    print("lists:\n{}".format(lists))
    if lists.size < 1: return
    width = (1.0 - padding) / num_sets
    #print("x_labels: {}".format(x_labels))
    
    # show each list as a set of bar plots so that corresponding elements in 
    # each list will be grouped together as bar groups
    for i in range(num_sets):
        err = None if errs is None or errs.size < 1 else errs[i]
        #print("lens: {}, {}".format(len(lists[i]), len(x_labels)))
        #print("showing list: {}, err: {}".format(lists[i], err))
        num_bars = len(lists[i])
        err_dict = {"elinewidth": width * 20 / num_bars}
        bars.append(ax.bar(
            indices + width * i, lists[i], width=width, color=colors[i], 
            linewidth=0, yerr=err, error_kw=err_dict, align="edge"))
    ax.set_title(title)
    ax.set_ylabel(y_label)
    ax.set_xticks(indices + width * len(lists) / 2)
    
    # scale font size of x-axis labels by a sigmoid function to rapidly 
    # decrease size for larger numbers of labels so they don't overlap
    font_size = plt.rcParams["axes.titlesize"]
    font_size *= (math.atan(len(x_labels) / 3 - 5) * -2 / math.pi + 1) / 2
    font_dict = { "fontsize": font_size }
    #print("======>", font_dict)
    ax.set_xticklabels(
        x_labels, rotation=80, horizontalalignment="right", fontdict=font_dict)
    
    if list_names:
        ax.legend(bars, list_names, loc="best", fancybox=True, framealpha=0.5)

def plot_volumes(vol_stats, title=None, densities=False, show=True, 
                 groups=[""]):
    """Plot volumes and densities.
    
    Args:
        vol_stats: Tuple of volume stats as generated by 
            :func:``stats.volume_stats``.
        title: Title to display for the entire figure; defaults to None, in 
            while case a generic title will be given.
        densities: True if densities should be extracted and displayed from 
            the volumes dictionary; defaults to False.
        show: True if plots should be displayed; defaults to True.
        groups: List of groupings for each experiment. List length should be 
            equal to the number of values stored in each label's list in 
            ``volumes_dict``. Defaults to a list with an empty string, in 
            which case each label's value will be assumed to be a scalar 
            rather than a list of values.
    """
    # unpack volume stats
    groups_dict, names, means_keys, sem_keys, meas_keys, meas_units = vol_stats
    num_meas = len(meas_keys)
    
    # measurement units, assuming a base unit of microns
    unit = "mm"
    
    # setup legends and bar colors
    sides_names = ("Left", "Right")
    legend_names = []
    bar_colors = []
    i = 0
    groups_unique = np.unique(groups)
    for group_name in groups_unique:
        for side in sides_names:
            name = "{} {}".format(group_name, side) if group_name else side
            legend_names.append(name)
            bar_colors.append("C{}".format(i))
            i += 1
    
    # organize stats dictionary by measurements for bar plot format
    bar_stats = stats.vol_group_to_meas_dict(vol_stats, groups)
    
    # setup figure layout with single subplot for volumes only or 
    # side-by-side subplots with additional measurements if including densities
    fig = plt.figure()
    subplots_width = num_meas if densities else 1
    gs = gridspec.GridSpec(1, subplots_width)
    
    # generate bar plots
    for i in range(num_meas):
        if i > 0 and not densities: break
        ax = plt.subplot(gs[0, i])
        meas = meas_keys[i]
        # assume that meas_group 0 is means/count, 1 is errs
        meas_group = bar_stats[meas]
        meas_unit = meas_units[i].replace("\u00b5m", unit)
        legend = legend_names if i == 0 else None
        _bar_plots(
            ax, meas_group[0], meas_group[1], 
            legend, names, bar_colors, meas_unit, meas)  
    
    # finalize the image with title and tight layout
    if title is None:
        title = "Regional Volumes"
    fig.suptitle(title)
    gs.tight_layout(fig, rect=[0, 0, 1, 0.97]) # extra padding for title
    if config.savefig is not None:
        plt.savefig(title + "." + config.savefig)
    if show:
        plt.show()

def plot_lines(path_to_df, x_col, data_cols, linestyles=None, x_label=None, 
               y_label=None, title=None, show=True):
    """Plot line graph from Pandas data frame.
    
    Args:
        path_to_df: Path from which to read saved Pandas data frame.
            The figure will be saved to file if :attr:``config.savefig`` is 
            set, using this same path except with the savefig extension.
        x_col: Name of column to use for x.
        data_cols: Sequence of names to plot as separate lines.
        linestyles: Sequence of styles to use for each line; defaults to 
            None, in which case "-" will be used for all lines.
        x_label: Name of x-axis; defaults to None.
        y_label: Name of y-axis; defaults to None.
        title: Title of figure; defaults to None.
        show: True to display the image; otherwise, the figure will only 
            be saved to file, if :attr:``config.savefig`` is set.  
            Defaults to True.
    """
    # load data frame from CSV and setup figure
    df = pd.read_csv(path_to_df)
    fig = plt.figure()
    gs = gridspec.GridSpec(1, 1)
    ax = plt.subplot(gs[0, 0])
    
    # plot selected columns with corresponding styles
    x = df[x_col]
    for i, col in enumerate(data_cols):
        linestyle = linestyles[i] if linestyles else "-"
        ax.plot(
            x, df[col], color="C{}".format(i), linestyle=linestyles[i], 
            label=col.replace("_", " "))
    
    # add supporting plot components
    ax.legend(loc="best", fancybox=True, framealpha=0.5)
    if x_label: ax.set_xlabel(x_label)
    if y_label: ax.set_ylabel(y_label)
    if title: ax.set_title(title)
    gs.tight_layout(fig)
    
    # save and display
    if config.savefig is not None:
        plt.savefig(os.path.splitext(path_to_df)[0] + "." + config.savefig)
    if show: plt.show()

def plot_bars(path_to_df, data_cols=None, col_groups=None, legend_names=None, 
              y_label=None, title=None, show=True):
    """Plot grouped bars from Pandas data frame.
    
    Args:
        path_to_df: Path from which to read saved Pandas data frame.
            The figure will be saved to file if :attr:``config.savefig`` is 
            set, using this same path except with the savefig extension.
        data_cols: Sequence of names of columns to plot as separate sets 
            of bars, where each row is part of a separate group. Defaults 
            to None, which will use plot all columns after the first. 
            Matching columns with "_err" as suffix will be used for 
            error bars; if so, there should be an error column for 
            each data column.
        col_groups: Name of column specifying names of each group. 
            Defaults to None, which will use the first column for names.
        legend_names: Sequence of names for each set of bars. 
            Defaults to None, which will use ``data_cols`` for names.
        y_label: Name of y-axis; defaults to None.
        title: Title of figure; defaults to None, which will use  
            ``path_to_df`` to build the title.
        show: True to display the image; otherwise, the figure will only 
            be saved to file, if :attr:``config.savefig`` is set.  
            Defaults to True.
    """
    # load data frame from CSV and setup figure
    df = pd.read_csv(path_to_df)
    fig = plt.figure()
    gs = gridspec.GridSpec(1, 1)
    ax = plt.subplot(gs[0, 0])
    
    if data_cols is None:
        # default to using first col as group names, rest of cols as data
        cols = df.columns.values.tolist()
        col_groups = cols[0]
        data_cols = cols[1:]
    elif col_groups is None:
        # default to empty group
        col_groups = [""] * len(data_cols)
    if legend_names is None:
        # default to using data column names for names of each set of bars
        legend_names = [name.replace("_", " ") for name in data_cols]
    
    # build lists to plot
    lists = []
    errs = []
    bar_colors = []
    for i, col in enumerate(data_cols):
        # each column gives a set of bars, where each bar will be in a 
        # separate group; find error columns by suffix
        lists.append(df[col])
        col_err = col + "_err"
        if col_err in df:
            errs.append(df[col_err])
        bar_colors.append("C{}".format(i))
    
    # plot bars
    if len(errs) < 1: errs = None
    if title is None:
        title = os.path.splitext(
            os.path.basename(path_to_df))[0].replace("_", " ")
    _bar_plots(ax, lists, errs, legend_names, df[col_groups], bar_colors, 
               y_label, title)
    gs.tight_layout(fig, rect=[0.1, 0, 0.9, 1])
    
    # save and display
    if config.savefig is not None:
        plt.savefig(os.path.splitext(path_to_df)[0] + "." + config.savefig)
    if show: plt.show()

def setup_style():
    # setup Matplotlib parameters/styles
    #print(plt.style.available)
    plt.style.use("seaborn")
    pylab.rcParams.update(config.rc_params)

if __name__ == "__main__":
    # set up command-line args and plotting style
    from clrbrain import cli
    cli.main(True)
    setup_style()
    
    if config.plot_2d == config.PLOT_2D_TYPES[0]:
        # plot smoothing metrics
        path = lib_clrbrain.combine_paths(
            config.prefix, config.PATH_SMOOTHING_METRICS)
        plot_lines(
            path, "filter", 
            ("roughness", "compacted", "displaced", "smoothing_quality", "SA_to_vol", 
             "label_loss"), 
            (":", "--", "--", "-", "-", "-"), "Smoothing Filter Size", 
            "Fractional Change", "Label Smoothing", not config.no_show)
    
    elif config.plot_2d == config.PLOT_2D_TYPES[1]:
        # generiic barplot
        plot_bars(config.filename, show=(not config.no_show))
