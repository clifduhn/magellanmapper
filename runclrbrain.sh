#!/bin/bash
# Template for running Clrbrain
# Author: David Young 2017, 2018

################################################
# Sample scenarios and workflows for Clrbrain
#
# Use this file as a template for your own scenarios. Edit path 
# variables with your own file paths. Change the indices of the 
# pathway flags to turn various parts on/off or to select the 
# desired pathway type.
################################################



####################################
# REPLACE WITH SETTINGS FOR YOUR IMAGE

# full path to original image, assumed to be within a directory 
# that names the experiment and also used for S3; eg 
# "/data/exp_yyyy-mm-dd/WT-cortex.czi"
IMG="/path/to/your/image"

# parent path of image file in cloud such as AWS S3; eg
# "MyName/ClearingExps", where the image would be found in 
# $S3_DIR/exp_yyyy-mm-dd
S3_DIR="path/to/your/bucket/artifact"

# Replace microscope type with available profiles, such as "lightsheet", 
# "2p_20x", or "lightsheet_v02", or with modifiers, such as 
# "lightsheet_contrast" or "lightsheet_contrast_cytoplasm". Multiple 
# profiles can also be given for multiple channels, such as 
# "lightsheet lightsheet_cytoplasm" for a nuclear marker in channel 0 
# and cytoplasmic marker in channel 1
MICROSCOPE="lightsheet"

# Choose whether to show GUI, in which case rest of pathways will be 
# ignored; replace ROI offset/size with desired coordinates/dimensions 
# in x,y,z format
gui=0
offset=30,30,8
size=70,70,10

# Choose stitch pathway index, or "" for none
STITCH_PATHWAYS=("stitching" "bigstitcher")
stitch_pathway="${STITCH_PATHWAYS[1]}"

# Choose rescale pathway index, or "" for none
TRANSPOSE_PATHWAYS=("rescale")
transpose_pathway="${TRANSPOSE_PATHWAYS[0]}"
scale=0.05 # rescaling factor
plane="" # xy, yz, zy, or leave empty
animation="" # gif or mp4

# Choose whole image processing index, or "" for none
WHOLE_IMG_PROCS=("local" "pull_from_s3")
whole_img_proc="${WHOLE_IMG_PROCS[0]}"

# Choose whether to upload all resulting files to AWS S3
upload=0 # 0 for no, 1 to upload



####################################
# Script setup

# Parsing names from your image path
OUT_DIR="`dirname $IMG`"
EXP="`basename $OUT_DIR`"
NAME="`basename $IMG`"
IMG_PATH_BASE="${OUT_DIR}/${NAME%.*}"
EXT="${IMG##*.}"

# run from script's directory
BASE_DIR="`dirname $0`"
cd "$BASE_DIR"
echo $PWD



####################################
# Graphical display

if [[ $gui -eq 1 ]]; then
    # Run Clrbrain GUI, importing the image into Numpy-based format that 
    # Clrbrain can read if not available. A few additional scenarios are
    # also shown, currently commented out. The script will exit after 
    # displaying the GUI.

    # Import raw image stack into Numpy array if it doesn't exist already
    python -u -m clrbrain.cli --img "$IMG" --channel 0 --proc importonly
    
    # Load ROI, starting at the given offset and ROI size
    ./run --img "$IMG" --channel 0 --offset $offset --size $size --savefig pdf --microscope "$MICROSCOPE"
    
    # Extract a single z-plane
    #python -u -m clrbrain.cli --img "$IMG" --proc extract --channel 0 --offset 0,0,0 -v --savefig jpeg --microscope "$MICROSCOPE"
    
    # Process a sub-stack and load it
    substack_offset=100,800,410
    substack_size=800,100,48
    #python -m clrbrain.cli --img "$IMG" --proc processing_mp --channel 0 -v --offset $substack_offset --size $substack_size --microscope "$MICROSCOPE"
    IMG_ROI="${IMG_PATH_BASE}_(${substack_offset})x(${substack_size}).${EXT}"
    #./run --img "$IMG_ROI" -v --channel 0 -v --proc load --offset $substack_offset --size $substack_size --savefig pdf --microscope "$MICROSCOPE"
    
    exit 0
fi


####################################
# Stitching Workflow

# Replace with your lens objective settings
RESOLUTIONS="0.913,0.913,4.935"
MAGNIFICATION="5.0"
ZOOM="1.0"

if [[ "$stitch_pathway" != "" && ! -e "$IMG" ]]; then
    # Get large, unstitched image file from cloud, where the fused (all 
    # illuminators merged) image is used for the Stitching pathway, and 
    # the unfused, original image is used for the BigStitcher pathway
    mkdir $OUT_DIR
    aws s3 cp s3://"${S3_DIR}/${EXP}/${NAME}" $OUT_DIR
fi

out_name_base=""
clr_img=""
if [[ "$stitch_pathway" == "${STITCH_PATHWAYS[0]}" ]]; then
    # ALTERNATIVE 1: Stitching plugin (old)
    
    OUT_NAME_BASE="${NAME%.*}_stitched"
    TIFF_DIR="${OUT_DIR}/${OUT_NAME_BASE}"
    
    # Replace the tile parameters with your image's setup; set up tile 
    # configuration manually and compute alignment refinement
    python -m stitch.tile_config --img "$NAME" --target_dir "$OUT_DIR" --cols 6 --rows 7 --size 1920,1920,1000 --overlap 0.1 --directionality bi --start_direction right
    ./stitch.sh -f "$IMG" -o "$TIFF_DIR" -w 0
    
    # Before the next steps, please manually check alignments to ensure that they 
    # fit properly, especially since unregistered tiles may be shifted to (0, 0, 0)
    ./stitch.sh -f "$IMG" -o "$TIFF_DIR" -w 1
    python -u -m clrbrain.cli --img "$TIFF_DIR" --res "$RESOLUTIONS" --mag "$MAGNIFICATION" --zoom "$ZOOM" -v --channel 0 --proc importonly
    clr_img="${OUT_DIR}/${OUT_NAME_BASE}.${EXT}"
    
elif [[ "$stitch_pathway" == "${STITCH_PATHWAYS[1]}" ]]; then
    # ALTERNATIVE 2: BigStitcher plugin
    
    OUT_NAME_BASE="${NAME%.*}_bigstitched"
    
    # Import file into BigStitcher HDF5 format (warning: large file, just 
    # under size of original file) and find alignments
    ./stitch.sh -f "$IMG" -b -w 0
    
    # Before writing stitched file, advise checking alignments; when 
    # satisfied, then run this fusion step
    ./stitch.sh -f "$IMG" -b -w 1
    
    # Rename output file(s):
    FUSED="fused_tp_0"
    for f in ${OUT_DIR}/${FUSED}*.tif; do mv $f ${f/$FUSED/$OUT_NAME_BASE}; done
    
    # Import stacked TIFF file(s) into Numpy arrays for Clrbrain
    python -u -m clrbrain.cli --img ""${OUT_DIR}/${OUT_NAME_BASE}.tiff"" --res "$RESOLUTIONS" --mag "$MAGNIFICATION" --zoom "$ZOOM" -v --proc importonly
    clr_img="${OUT_DIR}/${OUT_NAME_BASE}.${EXT}"
fi

# At this point, you can delete the TIFF image since it has been exported into a Numpy-based 
# format for loading into Clrbrain


####################################
# Transpose/Resize Image Workflow


clr_img_base="${clr_img%.*}"

if [[ "$transpose_pathway" == "${TRANSPOSE_PATHWAYS[0]}" ]]; then
    img_transposed=""
    if [[ "$plane" != "" ]]; then
        # Both rescale and transpose an image from z-axis (xy plane) to x-axis (yz plane) orientation
        python -u -m clrbrain.cli --img "$clr_img" --proc transpose --rescale ${scale} --plane "$plane"
        img_transposed="${clr_img_base}_plane${plane}_scale${scale}.${EXT}"
    else
        # Rescale an image to downsample by the scale factor only
        python -u -m clrbrain.cli --img "$clr_img" --proc transpose --rescale ${scale}
        img_transposed="${clr_img_base}_scale${scale}.${EXT}"
    fi
    
    if [[ "$animation" != "" ]]; then
        # Export transposed image to an animated GIF or MP4 video (requires ImageMagick)
        scale=1.0
        python -u -m clrbrain.cli --img "$img_transposed" --proc animated --interval 5 --rescale ${scale} --savefig "$animation"
    fi
fi


####################################
# Whole Image Processing Workflow

if [[ "$whole_img_proc" == "${WHOLE_IMG_PROCS[0]}" ]]; then
    # Process an entire image locally on 1st channel, chunked into multiple 
    # smaller stacks to minimize RAM usage and multiprocessed for efficiency
    python -u -m clrbrain.cli --img "$clr_img" --proc processing_mp --channel 0 --microscope "$MICROSCOPE"

elif [[ "$whole_img_proc" == "${WHOLE_IMG_PROCS[1]}" ]]; then
    # Similar processing but integrated with S3 access from AWS (run from 
    # within EC2 instance)
    ./process_aws.sh -f "$clr_img" -s $S3_DIR --  --microscope "$MICROSCOPE" --channel 0
fi


####################################
# Upload stitched image to cloud

if [[ $upload -eq 1 ]]; then
    # upload all resulting files to S3
    aws s3 cp $OUT_DIR s3://"${S3_DIR}/${EXP}" --recursive --exclude "*" --include *.npz
fi

exit 0
