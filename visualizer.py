#!/bin/bash
# 3D image visualization
# Author: David Young, 2017

import sys
import numpy as np
import math
from time import time

from traits.api import HasTraits, Range, Instance, \
                    on_trait_change, Button, Int, Array, push_exception_handler
from traitsui.api import View, Item, HGroup, VGroup, Handler, RangeEditor
from tvtk.pyface.scene_editor import SceneEditor
from mayavi.tools.mlab_scene_model import MlabSceneModel
from mayavi.core.ui.mayavi_scene import MayaviScene
import matplotlib.pylab as pylab

import importer
import detector
import plot_3d
import plot_2d

filename = "../../Downloads/P21_L5_CONT_DENDRITE.czi"
filename = "../../Downloads/Rbp4cre_halfbrain_4-28-16_Subset3.czi"
#filename = "../../Downloads/Rbp4cre_4-28-16_Subset3_2.sis"
#filename = "/Volumes/Siavash/CLARITY/P3Ntsr1cre-tdTomato_11-10-16/Ntsr1cre-tdTomato.czi"
series = 0 # arbitrary series for demonstration
channel = 0 # channel of interest
roi_size = [100, 100, 25]
offset = None

params = {'legend.fontsize': 'small',
         'axes.labelsize': 'small',
         'axes.titlesize':'xx-small',
         'xtick.labelsize':'small',
         'ytick.labelsize':'small'}

ARG_OFFSET = "offset"
ARG_CHANNEL = "channel"
ARG_SERIES = "series"
ARG_SIDES = "sides"
ARG_3D = "3d"

for arg in sys.argv:
    arg_split = arg.split("=")
    if len(arg_split) == 1:
        print("Skipped argument: {}".format(arg_split[0]))
    elif len(arg_split) >= 2:
        if arg_split[0] == ARG_OFFSET:
            offset_split = arg_split[1].split(",")
            if len(offset_split) >= 3:
                offset = tuple(int(i) for i in offset_split)
                print("Set offset: {}".format(offset))
            else:
                print("Offset ({}) should be given as 3 values (x, y, z)"
                      .format(arg_split[1]))
        elif arg_split[0] == ARG_CHANNEL:
            channel = int(arg_split[1])
        elif arg_split[0] == ARG_SERIES:
            series = int(arg_split[1])
        elif arg_split[0] == ARG_SIDES:
            sides_split = arg_split[1].split(",")
            if len(sides_split) >= 3:
                roi_size = tuple(int(i) for i in sides_split)
                print("Set roi_size: {}".format(roi_size))
            else:
                print("Sides ({}) should be given as 3 values (x, y, z)"
                      .format(arg_split[1]))
        elif arg_split[0] == ARG_3D:
            if arg_split[1] in plot_3d.MLAB_3D_TYPES:
                plot_3d.set_mlab_3d(arg_split[1])
                print("3D rendering set to {}".format(arg_split[1]))
            else:
                print("Did not recognize 3D rendering type: {}"
                      .format(arg_split[1]))

def _fig_title():
    i = filename.rfind("/")
    title = filename
    if i == -1:
        i = title.rfind("\\")
    if i != -1 and len(title) > i + 1:
        title = title[(i + 1):]
    title = ("{}, series: {}\n"
             "offset: {}, ROI size: {}").format(title, series, 
                                                offset, roi_size)
    return title

class VisHandler(Handler):
    """Simple handler for Visualization object events.
    
    Closes the JVM when the window is closed.
    """
    def closed(self, info, is_ok):
        importer.jb.kill_vm()

class Visualization(HasTraits):
    """GUI for choosing a region of interest and segmenting it.
    
    TraitUI-based graphical interface for selecting dimensions of an
    image to view and segment.
    
    Attributes:
        x_low, x_high, ...: Low and high values for each offset.
        x_offset: Integer trait for x-offset.
        y_offset: Integer trait for y-offset.
        z_offset: Integer trait for z-offset.
        scene: The main scene
        btn_redraw_trait: Button editor for drawing the reiong of 
            interest.
        btn_segment_trait: Button editor for segmenting the ROI.
        roi: The ROI.
    """
    x_low = 0
    x_high = 100
    y_low = 0
    y_high = 100
    z_low = 0
    z_high = 100
    x_offset = Int
    y_offset = Int
    z_offset = Int
    roi_array = Array(Int, shape=(1, 3))
    scene = Instance(MlabSceneModel, ())
    btn_redraw_trait = Button("Redraw")
    btn_segment_trait = Button("Segment")
    btn_2d_trait = Button("2D Plots")
    roi = None
    
    def __init__(self):
        # Do not forget to call the parent's __init__
        HasTraits.__init__(self)
        # dimension max values in pixels
        size = image5d.shape
        self.z_high = size[1]
        self.y_high = size[2]
        self.x_high = size[3]
        curr_offset = offset
        # apply user-defined offsets
        if curr_offset is not None:
            self.x_offset = curr_offset[0]
            self.y_offset = curr_offset[1]
            self.z_offset = curr_offset[2]
        else:
            print("No offset, using standard one")
            curr_offset = self._curr_offset()
            #self.roi = show_roi(image5d, self, cube_len=cube_len)
        self.roi_array[0] = roi_size
        self.roi = plot_3d.show_roi(image5d, self, self.roi_array[0], offset=curr_offset)
        #plot_2d.plot_2d_stack(_fig_title(), image5d, self.roi_array[0], curr_offset)
        #detector.segment_roi(self.roi, self)
    
    @on_trait_change('x_offset,y_offset,z_offset')
    def update_plot(self):
        print("x: {}, y: {}, z: {}".format(self.x_offset, self.y_offset, self.z_offset))
    
    def _btn_redraw_trait_fired(self):
        # ensure that cube dimensions don't exceed array
        size = image5d.shape
        if self.x_offset + roi_size[0] > size[3]:
            self.x_offset = size[3] - roi_size[0]
        if self.y_offset + roi_size[1] > size[2]:
            self.y_offset = size[2] - roi_size[1]
        if self.z_offset + roi_size[2] > size[1]:
            self.z_offset = size[1] - roi_size[2]
        
        # show updated region of interest
        curr_offset = self._curr_offset()
        curr_roi_size = self.roi_array[0]
        print(offset)
        self.roi = plot_3d.show_roi(image5d, self, curr_roi_size, offset=curr_offset)
    
    def _btn_segment_trait_fired(self):
        #print(Visualization.roi)
        detector.segment_roi(self.roi, self)
    
    def _btn_2d_trait_fired(self):
        curr_offset = self._curr_offset()
        curr_roi_size = self.roi_array[0].astype(int)
        print(curr_roi_size)
        plot_2d.plot_2d_stack(_fig_title(), image5d, curr_roi_size, curr_offset)
    
    def _curr_offset(self):
        return (self.x_offset, self.y_offset, self.z_offset)
    
    # the layout of the dialog created
    view = View(
        Item(
            'scene', 
            editor=SceneEditor(scene_class=MayaviScene),
            height=500, width=500, show_label=False
        ),
        VGroup(
            Item("roi_array", label="ROI dimensions (x,y,z)"),
            Item(
                "x_offset",
                editor=RangeEditor(
                    low_name="x_low",
                    high_name="x_high",
                    mode="slider")
            ),
            Item(
                "y_offset",
                editor=RangeEditor(
                    low_name="y_low",
                    high_name="y_high",
                    mode="slider")
            ),
            Item(
                "z_offset",
                editor=RangeEditor(
                    low_name="z_low",
                    high_name="z_high",
                    mode="slider")
            )
        ),
        HGroup(
            Item("btn_redraw_trait", show_label=False), 
            Item("btn_segment_trait", show_label=False), 
            Item("btn_2d_trait", show_label=False)
        ),
        handler=VisHandler(),
        title = "clrbrain",
        resizable = True
    )

# loads the image and GUI
importer.start_jvm()
#names, sizes = parse_ome(filename)
#sizes = find_sizes(filename)
image5d = importer.read_file(filename, series, channel) #, z_max=cube_len)
pylab.rcParams.update(params)
push_exception_handler(reraise_exceptions=True)
visualization = Visualization()
visualization.configure_traits()
