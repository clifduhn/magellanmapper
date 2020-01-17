#!/bin/bash
# Region labels export to data frames and CSV files
# Author: David Young, 2019
"""Region labels export to data frames and CSV files.

Convert regions from ontology files or atlases to data frames.
"""
import csv
import multiprocessing as mp
from collections import OrderedDict
from time import time

import SimpleITK as sitk
import numpy as np
import pandas as pd

from magmap.settings import config
from magmap.io import libmag
from magmap.io import np_io
from magmap.atlas import ontology
from magmap.cv import cv_nd
from magmap.io import df_io
from magmap.io import sitk_io
from magmap.stats import vols


def export_region_ids(labels_ref_lookup, path, level):
    """Export region IDs from annotation reference reverse mapped dictionary 
    to CSV file.
    
    Args:
        labels_ref_lookup: The labels reference lookup, assumed to be an 
            OrderedDict generated by :func:`ontology.create_reverse_lookup` 
            to look up by ID while preserving key order to ensure that 
            parents of any child will be reached prior to the child.
        path: Path to output CSV file; if does not end with ``.csv``, it will 
            be added.
        level: Level at which to find parent for each label. If None, 
            a parent level of -1 will be used, and label IDs will be 
            taken from the labels image rather than the full set of 
            labels from the ``labels_ref_lookup``.
    
    Returns:
        Pandas data frame of the region IDs and corresponding names.
    """
    ext = ".csv"
    if not path.endswith(ext): path += ext
    
    # find parents for label at the given level
    parent_level = -1 if level is None else level
    label_parents = ontology.labels_to_parent(labels_ref_lookup, parent_level)
    
    cols = ("Region", "RegionAbbr", "RegionName", "Level", "Parent")
    data = OrderedDict()
    label_ids = sitk_io.find_atlas_labels(
        config.load_labels, level, labels_ref_lookup)
    for key in label_ids:
        # does not include laterality distinction, only using original IDs
        if key <= 0: continue
        label = labels_ref_lookup[key]
        # ID of parent at label_parents' level
        parent = label_parents[key]
        vals = (key, label[ontology.NODE][config.ABAKeys.ACRONYM.value],
                label[ontology.NODE][config.ABAKeys.NAME.value],
                label[ontology.NODE][config.ABAKeys.LEVEL.value], parent)
        for col, val in zip(cols, vals):
            data.setdefault(col, []).append(val)
    data_frame = df_io.dict_to_data_frame(data, path)
    return data_frame


def export_region_network(labels_ref_lookup, path):
    """Export region network file showing relationships among regions 
    according to the SIF specification.
    
    See http://manual.cytoscape.org/en/stable/Supported_Network_File_Formats.html#sif-format
    for file format information.
    
    Args:
        labels_ref_lookup: The labels reference lookup, assumed to be an 
            OrderedDict generated by :func:`ontology.create_reverse_lookup` 
            to look up by ID while preserving key order to ensure that 
            parents of any child will be reached prior to the child.
        path: Path to output SIF file; if does not end with ``.sif``, it will 
            be added.
    """
    ext = ".sif"
    if not path.endswith(ext): path += ext
    network = {}
    for key in labels_ref_lookup.keys():
        if key < 0: continue  # only use original, non-neg region IDs
        label = labels_ref_lookup[key]
        parents = label.get(ontology.PARENT_IDS)
        if parents:
            for parent in parents[::-1]:
                # work backward since closest parent listed last
                #print("{} looking for parent {} in network".format(key, parent))
                network_parent = network.get(parent)
                if network_parent is not None:
                    # assume that all parents will have already been entered 
                    # into the network dict since the keys were entered in 
                    # hierarchical order and maintain their order of entry
                    network_parent.append(key)
                    break
        # all regions have a node, even if connected to no one
        network[key] = []
    
    with open(path, "w", newline="") as csv_file:
        stats_writer = csv.writer(csv_file, delimiter=" ")
        # each region will have a line along with any of its immediate children
        for key in network.keys():
            children = network[key]
            row = [str(key)]
            if children:
                row.extend(["pp", *children])
            stats_writer.writerow(row)
    print("exported region network: \"{}\"".format(path))


def export_common_labels(img_paths, output_path):
    """Export data frame combining all label IDs from the given atlases, 
    showing the presence of labels in each atlas.
    
    Args:
        img_paths: Image paths from which to load the corresponding 
            labels images.
        output_path: Path to export data frame to .csv.
    
    Returns:
        Data frame with label IDs as indices, column for each atlas, and 
        cells where 1 indicates that the given atlas has the corresponding 
        label.
    """
    labels_dict = {}
    for img_path in img_paths:
        name = libmag.get_filename_without_ext(img_path)
        labels_np = sitk_io.load_registered_img(
            img_path, config.RegNames.IMG_LABELS.value)
        # only use pos labels since assume neg labels are merely mirrored
        labels_unique = np.unique(labels_np[labels_np >= 0])
        labels_dict[name] = pd.Series(
            np.ones(len(labels_unique), dtype=int), index=labels_unique)
    df = pd.DataFrame(labels_dict)
    df.sort_index()
    df.to_csv(output_path)
    print("common labels exported to {}".format(output_path))
    return df


def make_density_image(img_path, scale=None, shape=None, suffix=None, 
                       labels_img_sitk=None):
    """Make a density image based on associated blobs.
    
    Uses the shape of the registered labels image by default to set 
    the voxel sizes for the blobs.
    
    Args:
        img_path: Path to image, which will be used to indentify the blobs file.
        scale: Rescaling factor as a scalar value to find the corresponding 
            full-sized image. Defaults to None to use the register 
            setting ``target_size`` instead if available, falling back 
            to load the full size image to find its shape if necessary.
        shape: Final shape size; defaults to None to use the shape of 
            the labels image.
        suffix: Modifier to append to end of ``img_path`` basename for 
            registered image files that were output to a modified name; 
            defaults to None.
        labels_img_sitk: Labels image as a SimpleITK ``Image`` object; 
            defaults to None, in which case the registered labels image file 
            corresponding to ``img_path`` with any ``suffix`` modifier 
            will be opened.
    
    Returns:
        Tuple of the density image as a Numpy array in the same shape as 
        the opened image; Numpy array of blob IDs; and the original 
        ``img_path`` to track such as for multiprocessing.
    """
    mod_path = img_path
    if suffix is not None:
        mod_path = libmag.insert_before_ext(img_path, suffix)
    if labels_img_sitk is None:
        labels_img_sitk = sitk_io.load_registered_img(
            mod_path, config.RegNames.IMG_LABELS.value, get_sitk=True)
    labels_img = sitk.GetArrayFromImage(labels_img_sitk)
    # load blobs
    blobs, scaling, _ = np_io.load_blobs(img_path, labels_img.shape, scale)
    if shape is not None:
        # scale blobs to an alternative final size
        scaling = np.divide(shape, np.divide(labels_img.shape, scaling))
        labels_spacing = np.multiply(
            labels_img_sitk.GetSpacing()[::-1], 
            np.divide(labels_img.shape, shape))
        labels_img = np.zeros(shape, dtype=labels_img.dtype)
        labels_img_sitk.SetSpacing(labels_spacing[::-1])
    print("using scaling: {}".format(scaling))
    # annotate blobs based on position
    blobs_ids, coord_scaled = ontology.get_label_ids_from_position(
        blobs[:, :3], labels_img, scaling, 
        return_coord_scaled=True)
    print("blobs_ids: {}".format(blobs_ids))
    
    # build heat map to store densities per label px and save to file
    heat_map = cv_nd.build_heat_map(labels_img.shape, coord_scaled)
    out_path = sitk_io.reg_out_path(
        mod_path, config.RegNames.IMG_HEAT_MAP.value)
    print("writing {}".format(out_path))
    heat_map_sitk = sitk_io.replace_sitk_with_numpy(labels_img_sitk, heat_map)
    sitk.WriteImage(heat_map_sitk, out_path, False)
    return heat_map, blobs_ids, img_path


def make_density_images_mp(img_paths, scale=None, shape=None, suffix=None):
    """Make density images for a list of files as a multiprocessing 
    wrapper for :func:``make_density_image``
    
    Args:
        img_path: Path to image, which will be used to indentify the blobs file.
        scale: Rescaling factor as a scalar value. If set, the corresponding 
            image for this factor will be opened. If None, the full size 
            image will be used. Defaults to None.
        suffix: Modifier to append to end of ``img_path`` basename for 
            registered image files that were output to a modified name; 
            defaults to None.
    """
    start_time = time()
    pool = mp.Pool()
    pool_results = []
    for img_path in img_paths:
        print("making image", img_path)
        pool_results.append(pool.apply_async(
            make_density_image, args=(img_path, scale, shape, suffix)))
    heat_maps = []
    for result in pool_results:
        _, _, path = result.get()
        print("finished {}".format(path))
    pool.close()
    pool.join()
    print("time elapsed for making density images:", time() - start_time)


def make_labels_diff_img(img_path, df_path, meas, fn_avg, prefix=None, 
                         show=False, level=None, meas_path_name=None, 
                         col_wt=None):
    """Replace labels in an image with the differences in metrics for 
    each given region between two conditions.
    
    Args:
        img_path: Path to the base image from which the corresponding 
            registered image will be found.
        df_path: Path to data frame with metrics for the labels.
        meas: Name of colum in data frame with the chosen measurement.
        fn_avg: Function to apply to the set of measurements, such as a mean. 
            Can be None if ``df_path`` points to a stats file from which 
            to extract metrics directly in :meth:``vols.map_meas_to_labels``.
        prefix: Start of path for output image; defaults to None to 
            use ``img_path`` instead.
        show: True to show the images after generating them; defaults to False.
        level: Ontological level at which to look up and show labels. 
            Assume that labels level image corresponding to this value 
            has already been generated by :meth:``make_labels_level_img``. 
            Defaults to None to use only drawn labels.
        meas_path_name: Name to use in place of `meas` in output path; 
            defaults to None.
        col_wt (str): Name of column to use for weighting; defaults to None.
    """
    # load labels image and data frame before generating map for the 
    # given metric of the chosen measurement
    print("Generating labels difference image for", meas, "from", df_path)
    reg_name = (config.RegNames.IMG_LABELS.value if level is None 
                else config.RegNames.IMG_LABELS_LEVEL.value.format(level))
    labels_sitk = sitk_io.load_registered_img(img_path, reg_name, get_sitk=True)
    labels_np = sitk.GetArrayFromImage(labels_sitk)
    df = pd.read_csv(df_path)
    labels_diff = vols.map_meas_to_labels(
        labels_np, df, meas, fn_avg, reverse=True, col_wt=col_wt)
    if labels_diff is None: return
    labels_diff_sitk = sitk_io.replace_sitk_with_numpy(labels_sitk, labels_diff)
    
    # save and show labels difference image using measurement name in 
    # output path or overriding with custom name
    meas_path = meas if meas_path_name is None else meas_path_name
    reg_diff = libmag.insert_before_ext(
        config.RegNames.IMG_LABELS_DIFF.value, meas_path, "_")
    if fn_avg is not None:
        # add function name to output path if given
        reg_diff = libmag.insert_before_ext(
            reg_diff, fn_avg.__name__, "_")
    imgs_write = {reg_diff: labels_diff_sitk}
    out_path = prefix if prefix else img_path
    sitk_io.write_reg_images(imgs_write, out_path)
    if show:
        for img in imgs_write.values():
            if img: sitk.Show(img)


def make_labels_level_img(img_path, level, prefix=None, show=False):
    """Replace labels in an image with their parents at the given level.
    
    Labels that do not fall within a parent at that level will remain in place.
    
    Args:
        img_path: Path to the base image from which the corresponding 
            registered image will be found.
        level: Ontological level at which to group child labels. 
        prefix: Start of path for output image; defaults to None to 
            use ``img_path`` instead.
        show: True to show the images after generating them; defaults to False.
    """
    # load original labels image and setup ontology dictionary
    labels_sitk = sitk_io.load_registered_img(
        img_path, config.RegNames.IMG_LABELS.value, get_sitk=True)
    labels_np = sitk.GetArrayFromImage(labels_sitk)
    ref = ontology.load_labels_ref(config.load_labels)
    labels_ref_lookup = ontology.create_aba_reverse_lookup(ref)
    
    ids = list(labels_ref_lookup.keys())
    for key in ids:
        keys = [key, -1 * key]
        for region in keys:
            if region == 0: continue
            # get ontological label
            label = labels_ref_lookup[abs(region)]
            label_level = label[ontology.NODE][config.ABAKeys.LEVEL.value]
            if label_level == level:
                # get children (including parent first) at given level 
                # and replace them with parent
                label_ids = ontology.get_children_from_id(
                    labels_ref_lookup, region)
                labels_region = np.isin(labels_np, label_ids)
                print("replacing labels within", region)
                labels_np[labels_region] = region
    labels_level_sitk = sitk_io.replace_sitk_with_numpy(labels_sitk, labels_np)
    
    # generate an edge image at this level
    labels_edge = vols.make_labels_edge(labels_np)
    labels_edge_sikt = sitk_io.replace_sitk_with_numpy(labels_sitk, labels_edge)
    
    # write and optionally display labels level image
    imgs_write = {
        config.RegNames.IMG_LABELS_LEVEL.value.format(level): labels_level_sitk, 
        config.RegNames.IMG_LABELS_EDGE_LEVEL.value.format(level): 
            labels_edge_sikt, 
    }
    out_path = prefix if prefix else img_path
    sitk_io.write_reg_images(imgs_write, out_path)
    if show:
        for img in imgs_write.values():
            if img: sitk.Show(img)
