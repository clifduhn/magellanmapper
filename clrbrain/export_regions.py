#!/bin/bash
# Region labels export to data frames and CSV files
# Author: David Young, 2019
"""Region labels export to data frames and CSV files.

Convert regions from ontology files or atlases to data frames.
"""
import csv
from collections import OrderedDict

from clrbrain import config
from clrbrain import ontology
from clrbrain import stats
from clrbrain import sitk_io


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
    data_frame = stats.dict_to_data_frame(data, path)
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
        if key < 0: continue # only use original, non-neg region IDs
        label = labels_ref_lookup[key]
        parents = label.get(ontology.PARENT_IDS)
        if parents:
            for parent in parents[::-1]:
                # work backward since closest parent listed last
                print("{} looking for parent {} in network".format(key, parent))
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
    print("output region network to {}".format(path))
