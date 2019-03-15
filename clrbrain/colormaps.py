#!/bin/bash
# Colormaps for Clrbrain
# Author: David Young, 2018, 2019
"""Custom colormaps for Clrbrain.
"""

import numpy as np
from matplotlib import colors

from clrbrain import config
from clrbrain import lib_clrbrain

CMAP_GRBK = colors.LinearSegmentedColormap.from_list(
    config.CMAP_GRBK_NAME, ["black", "green"])
CMAP_RDBK = colors.LinearSegmentedColormap.from_list(
    config.CMAP_RDBK_NAME, ["black", "red"])

class DiscreteColormap(colors.ListedColormap):
    """Extends :class:``matplotlib.colors.ListedColormap`` to generate a 
    discrete colormap and associated normalization object.
    
    Attributes:
        cmap_labels: Tuple of N lists of RGBA values, where N is equal 
            to the number of colors, with a discrete color for each 
            unique value in ``labels``.
        norm: Normalization object, which is of type 
            :class:``matplotlib.colors.NoNorm`` if indexing directly or 
            :class:``matplotlib.colors.BoundaryNorm`` if otherwise.
    """
    def __init__(self, labels=None, seed=None, alpha=150, index_direct=True, 
                 multiplier=255, offset=0, background=None):
        """Generate discrete colormap for labels using 
        :func:``discrete_colormap``.
        
        Args:
            labels: Labels of integers for which a distinct color should be 
                mapped to each unique label. Deafults to None, in which case 
                no colormap will be generated.
            seed: Seed for randomizer to allow consistent colormap between 
                runs; defaults to None.
            alpha: Transparency leve; defaults to 150 for semi-transparent.
            index_direct: True if the colormap will be indexed directly, which 
                assumes that the labels will serve as indexes to the colormap 
                and should span sequentially from 0, 1, 2, ...; defaults to 
                True. If False, a colormap will be generated for the full 
                range of integers between the lowest and highest label values, 
                inclusive.
            multiplier: Multiplier for random values generated for RGB values; 
                defaults to 255.
            offset: Offset to generated random numbers; defaults to 0.
            background: Tuple of (backround_label, (R, G, B, A)), where 
                background_label is the label value specifying the background, 
                and RGBA value will replace the color corresponding to that 
                label. Defaults to None.
        """
        if labels is None: return
        self.norm = None
        labels_unique = np.unique(labels).astype(np.float32)
        num_colors = len(np.unique(labels))
        # make first boundary slightly below first label to encompass it 
        # to avoid off-by-one errors that appear to occur when viewing an 
        # image with an additional extreme label
        labels_offset = 0.5
        labels_unique -= labels_offset
        # number of boundaries should be one more than number of labels to 
        # avoid need for interpolation of boundary bin numbers and 
        # potential merging of 2 extreme labels
        labels_unique = np.append(labels_unique, [labels_unique[-1] + 1])
        if index_direct:
            # asssume label vals increase by 1 from 0 until num_colors
            self.norm = colors.NoNorm()
        else:
            # labels themselves serve as bounds, allowing for large gaps 
            # between labels while assigning each label to a unique color
            self.norm = colors.BoundaryNorm(labels_unique, num_colors)
        self.cmap_labels = discrete_colormap(
            num_colors, alpha=alpha, prioritize_default=False, seed=seed, 
            multiplier=multiplier, offset=offset)
        if background is not None:
            # replace backgound label color with given color
            bkgdi = np.where(labels_unique == background[0] - labels_offset)
            if len(bkgdi) > 0 and bkgdi[0].size > 0:
                self.cmap_labels[bkgdi[0][0]] = background[1]
        #print(self.cmap_labels)
        self.make_cmap()
    
    def make_cmap(self):
        # listed rather than linear cmap since num of colors should equal num 
        # of possible vals, without requiring interpolation
        super(DiscreteColormap, self).__init__(
            self.cmap_labels / 255.0, "discrete_cmap")
    
    def modified_cmap(self, adjust):
        """Make a modified discrete colormap from itself.
        
        Args:
            adjust: Value by which to adjust RGB (not A) values.
        
        Returns:
            New ``DiscreteColormap`` instance with ``norm`` pointing to first 
            instance and ``cmap_labels`` incremented by the given value.
        """
        cmap = DiscreteColormap()
        # TODO: consider whether to copy instead
        cmap.norm = self.norm
        cmap.cmap_labels = np.copy(self.cmap_labels)
        # labels are uint8 so should already fit within RGB bounds; colors 
        # that exceed these bounds will likely have slightly different tones 
        # since RGB vals will not change uniformly
        cmap.cmap_labels[:, :3] += adjust
        cmap.make_cmap()
        return cmap

def discrete_colormap(num_colors, alpha=255, prioritize_default=True, 
                      seed=None, multiplier=255, offset=0):
    """Make a discrete colormap using :attr:``config.colors`` as the 
    starting colors and filling in the rest with randomly generated RGB values.
    
    Args:
        num_colors: Number of discrete colors to generate.
        alpha: Transparency level.
        prioritize_defaults: If True, the default colors from 
            :attr:``config.colors`` will replace the initial colormap elements; 
            defaults to True.
        seed: Random number seed; defaults to None, in which case no seed 
            will be set.
        multiplier: Multiplier for random values generated for RGB values; 
            defaults to 255.
        offset: Offset to generated random numbers; defaults to 0. The 
            final numbers will be in the range from offset to offset+multiplier.
    
    Returns:
        2D Numpy array in the format [[R, G, B, alpha], ...]. This colormap 
        will need to be converted into a Matplotlib colormap using 
        ``LinearSegmentedColormap.from_list`` to generate a map that can 
        be used directly in functions such as ``imshow``.
    """
    # generate random combination of RGB values for each number of colors, 
    # skewed by offset and limited by multiplier
    if seed is not None:
        np.random.seed(seed)
    cmap = (np.random.random((num_colors, 4)) 
            * multiplier + offset).astype(np.uint8)
    cmap[:, -1] = alpha # make slightly transparent
    if prioritize_default:
        # prioritize default colors by replacing first colors with default ones
        for i in range(len(config.colors)):
            if i >= num_colors:
                break
            cmap[i, :3] = config.colors[i]
    return cmap

def get_labels_discrete_colormap(labels_img, alpha_bkgd=255):
    """Get a default discrete colormap for a labels image, assuming that 
    background is 0, and the seed is determined by :attr:``config.seed``.
    
    Args:
        labels_img: Labels image as a Numpy array.
        alpha_bkgd: Background alpha level from 0 to 255; defaults to 255 
            to turn on background fully.
    
    Returns:
        :class:``DiscreteColormap`` object with a separate color for 
        each unique value in ``labels_img``.
    """
    return DiscreteColormap(
        labels_img, config.seed, 255, False, 150, 50, 
        (0, (0, 0, 0, alpha_bkgd)))

def get_borders_colormap(borders_img, labels_img, cmap_labels):
    """Get a colormap for borders, using corresponding labels with 
    intensity change to distinguish the borders.
    
    If the number of labels differs from that of the original colormap, 
    a new colormap will be generated instead.
    
    Args:
        borders_img: Borders image as a Numpy array, used to determine 
            the number of labels required. If this image has multiple 
            channels, a similar colormap with distinct intensity will 
            be made for each channel.
        labels_img: Labels image as a Numpy array, used to compare 
            the number of labels for each channel in ``borders_img``.
        cmap_labels: The original colormap on which the new colormaps 
            will be based.
    
    Returns:
        List of borders colormaps corresponding to the number of channels, 
        or None if ``borders_img`` is None
    """
    cmap_borders = None
    if borders_img is not None:
        if (np.unique(labels_img).size 
            == np.unique(borders_img).size):
            # get matching colors by using labels colormap as template, 
            # with brightest colormap for original (channel 0) borders
            channels = 1
            if borders_img.ndim >= 4:
                channels = borders_img.shape[-1]
            cmap_borders = [
                cmap_labels.modified_cmap(int(40 / (channel + 1)))
                for channel in range(channels)]
        else:
            # get a new colormap if borders image has different number 
            # of labels while still ensuring a transparent background
            cmap_borders = [get_labels_discrete_colormap(borders_img, 0)]
    return cmap_borders
