#!/usr/bin/env python3
# Copyright (c) Opendatalab. All rights reserved.
import os
import time
import argparse
import sys
from pathlib import Path
import torch.distributed as dist
from pdf2image import convert_from_path

from magic_pdf.data.data_reader_writer import FileBasedDataWriter, FileBasedDataReader
from magic_pdf.data.dataset import PymuDocDataset, ImageDataset, MultiImageDataset
from magic_pdf.model.doc_analyze_by_custom_model_llm import doc_analyze_llm
from magic_pdf.model.custom_model import MonkeyOCR


TASK_INSTRUCTIONS = {
    'text': 'Please output the text content from the image.',
    'formula': 'Please write out the expression of the formula in the image using LaTeX format.',
    'table': 'This is the image of a table. Please output the table in html format.'
}

def parse_folder(folder_path, output_dir, config_path, task=None, group_size=None):
    """
    Parse all PDF and image files in a folder
    
    Args:
        folder_path: Input folder path
        output_dir: Output directory
        config_path: Configuration file path
        task: Optional task type for single task recognition
        group_size: Number of images to group together as MultiImageDataset (None means process individually)
    """
    print(f"Starting to parse folder: {folder_path}")
    
    # Record start time for total processing time
    total_start_time = time.time()
    
    # Check if folder exists
    if not os.path.exists(folder_path):
        raise FileNotFoundError(f"Folder does not exist: {folder_path}")
    
    if not os.path.isdir(folder_path):
        raise ValueError(f"Path is not a directory: {folder_path}")
    
    # Find all supported files
    supported_extensions = {'.pdf', '.jpg', '.jpeg', '.png'}
    pdf_files = []
    image_files = []
    
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            file_ext = os.path.splitext(file)[1].lower()
            if file_ext == '.pdf':
                pdf_files.append(file_path)
            elif file_ext in {'.jpg', '.jpeg', '.png'}:
                image_files.append(file_path)
    
    pdf_files.sort()
    image_files.sort()
    
    # Initialize model once for all files
    print("Loading model...")
    MonkeyOCR_model = MonkeyOCR(config_path)
    
    successful_files = []
    failed_files = []
    
    # Process PDF files individually
    if pdf_files:
        print(f"Found {len(pdf_files)} PDF files to process:")
        for file_path in pdf_files:
            print(f"  - {file_path}")
        
        for i, file_path in enumerate(pdf_files, 1):
            print(f"\n{'='*60}")
            print(f"Processing PDF file {i}/{len(pdf_files)}: {os.path.basename(file_path)}")
            print(f"{'='*60}")
            
            try:
                if task:
                    result_dir = single_task_recognition(file_path, output_dir, MonkeyOCR_model, task)
                else:
                    result_dir = parse_file(file_path, output_dir, MonkeyOCR_model)
                
                successful_files.append(file_path)
                print(f"✅ Successfully processed: {os.path.basename(file_path)}")
                
            except Exception as e:
                failed_files.append((file_path, str(e)))
                print(f"❌ Failed to process {os.path.basename(file_path)}: {str(e)}")
    
    # Process image files
    if image_files:
        if group_size and group_size > 1:
            # Group images and process as MultiImageDataset
            print(f"Found {len(image_files)} image files to process in groups of {group_size}")
            
            # Create groups of images
            image_groups = []
            for i in range(0, len(image_files), group_size):
                group = image_files[i:i + group_size]
                image_groups.append(group)
            
            print(f"Created {len(image_groups)} image groups")
            
            for i, image_group in enumerate(image_groups, 1):
                print(f"\n{'='*60}")
                print(f"Processing image group {i}/{len(image_groups)} (contains {len(image_group)} images)")
                for img_path in image_group:
                    print(f"  - {os.path.basename(img_path)}")
                print(f"{'='*60}")
                
                try:
                    if task:
                        result_dir = single_task_recognition_group(image_group, output_dir, MonkeyOCR_model, task, folder_path)
                    else:
                        result_dir = parse_image_group(image_group, output_dir, MonkeyOCR_model, folder_path)
                    
                    successful_files.extend(image_group)
                    print(f"✅ Successfully processed image group {i}")
                    
                except Exception as e:
                    failed_files.extend([(path, str(e)) for path in image_group])
                    print(f"❌ Failed to process image group {i}: {str(e)}")
        else:
            # Process images individually
            print(f"Found {len(image_files)} image files to process individually:")
            for file_path in image_files:
                print(f"  - {file_path}")
            
            for i, file_path in enumerate(image_files, 1):
                print(f"\n{'='*60}")
                print(f"Processing image file {i}/{len(image_files)}: {os.path.basename(file_path)}")
                print(f"{'='*60}")
                
                try:
                    if task:
                        result_dir = single_task_recognition(file_path, output_dir, MonkeyOCR_model, task)
                    else:
                        result_dir = parse_file(file_path, output_dir, MonkeyOCR_model)
                    
                    successful_files.append(file_path)
                    print(f"✅ Successfully processed: {os.path.basename(file_path)}")
                    
                except Exception as e:
                    failed_files.append((file_path, str(e)))
                    print(f"❌ Failed to process {os.path.basename(file_path)}: {str(e)}")
    
    if not pdf_files and not image_files:
        print("No supported files found in the folder.")
        return
    
    # Calculate total processing time
    total_processing_time = time.time() - total_start_time
    
    # Summary
    total_files = len(pdf_files) + len(image_files)
    print(f"\n{'='*60}")
    print("PROCESSING SUMMARY")
    print(f"{'='*60}")
    print(f"Total files: {total_files}")
    print(f"Successful: {len(successful_files)}")
    print(f"Failed: {len(failed_files)}")
    print(f"Total processing time: {total_processing_time:.2f}s")
    
    if failed_files:
        print("\nFailed files:")
        for file_path, error in failed_files:
            print(f"  - {os.path.basename(file_path)}: {error}")
    
    return output_dir

def parse_image_group(image_paths, output_dir, MonkeyOCR_model, base_folder_path):
    """
    Parse a group of images using MultiImageDataset
    
    Args:
        image_paths: List of image file paths
        output_dir: Output directory
        MonkeyOCR_model: Pre-initialized model instance
        base_folder_path: Base folder path for maintaining relative structure
    """
    print(f"Starting to parse image group with {len(image_paths)} images")
    
    # Maintain relative path structure from base folder
    rel_path = os.path.relpath(os.path.dirname(image_paths[0]), base_folder_path)
    
    # Read all image files
    reader = FileBasedDataReader()
    image_bytes_list = []
    
    for image_path in image_paths:
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file does not exist: {image_path}")
        
        image_bytes = reader.read(image_path)
        image_bytes_list.append(image_bytes)
    
    # Create MultiImageDataset
    ds = MultiImageDataset(image_bytes_list)
    
    # Start inference with split_pages=True to get individual results
    print("Performing document parsing on image group...")
    start_time = time.time()
    
    infer_result = ds.apply(doc_analyze_llm, MonkeyOCR_model=MonkeyOCR_model, split_pages=True)
    
    parsing_time = time.time() - start_time
    print(f"Parsing time: {parsing_time:.2f}s")

    # Check if infer_result is a list (should be with split_pages=True)
    if isinstance(infer_result, list) and len(infer_result) == len(image_paths):
        print(f"Processing {len(infer_result)} images separately...")
        
        # Process each image result separately using original image names
        for img_idx, (page_infer_result, image_path) in enumerate(zip(infer_result, image_paths)):
            # Get original image name without extension
            image_name = '.'.join(os.path.basename(image_path).split(".")[:-1])
            
            # Create output directory for this specific image
            if rel_path == '.':
                image_local_md_dir = os.path.join(output_dir, image_name)
            else:
                image_local_md_dir = os.path.join(output_dir, rel_path, image_name)
            
            image_local_image_dir = os.path.join(image_local_md_dir, "images")
            image_dir = os.path.basename(image_local_image_dir)
            
            # Create image-specific directories
            os.makedirs(image_local_image_dir, exist_ok=True)
            os.makedirs(image_local_md_dir, exist_ok=True)
            
            # Create image-specific writers
            image_image_writer = FileBasedDataWriter(image_local_image_dir)
            image_md_writer = FileBasedDataWriter(image_local_md_dir)
            
            print(f"Processing image {img_idx + 1}/{len(infer_result)}: {image_name} - Output dir: {image_local_md_dir}")
            
            # Pipeline processing for this image
            image_pipe_result = page_infer_result.pipe_ocr_mode(image_image_writer, MonkeyOCR_model=MonkeyOCR_model)
            
            # Save image-specific results using original image name
            page_infer_result.draw_model(os.path.join(image_local_md_dir, f"{image_name}_model.pdf"))
            
            image_pipe_result.draw_layout(os.path.join(image_local_md_dir, f"{image_name}_layout.pdf"))

            image_pipe_result.draw_span(os.path.join(image_local_md_dir, f"{image_name}_spans.pdf"))

            image_pipe_result.dump_md(image_md_writer, f"{image_name}.md", image_dir)
            
            image_pipe_result.dump_content_list(image_md_writer, f"{image_name}_content_list.json", image_dir)

            image_pipe_result.dump_middle_json(image_md_writer, f'{image_name}_middle.json')
        
        print(f"All {len(infer_result)} images processed and saved in separate directories using original image names")
        
        # Return the base directory containing all individual image results
        if rel_path == '.':
            return output_dir
        else:
            return os.path.join(output_dir, rel_path)
    else:
        # Fallback: if split_pages didn't work as expected, use the old logic
        print("Warning: split_pages didn't return expected individual results, using group processing...")
        
        # Create group name based on first and last image names
        first_name = '.'.join(os.path.basename(image_paths[0]).split(".")[:-1])
        last_name = '.'.join(os.path.basename(image_paths[-1]).split(".")[:-1])
        group_name = f"{first_name}_to_{last_name}_group"
        
        if rel_path == '.':
            local_md_dir = os.path.join(output_dir, group_name)
        else:
            local_md_dir = os.path.join(output_dir, rel_path, group_name)
        
        local_image_dir = os.path.join(local_md_dir, "images")
        image_dir = os.path.basename(local_image_dir)
        os.makedirs(local_image_dir, exist_ok=True)
        os.makedirs(local_md_dir, exist_ok=True)
        
        print(f"Output dir: {local_md_dir}")
        image_writer = FileBasedDataWriter(local_image_dir)
        md_writer = FileBasedDataWriter(local_md_dir)
        
        # Pipeline processing for group result
        pipe_result = infer_result.pipe_ocr_mode(image_writer, MonkeyOCR_model=MonkeyOCR_model)
        
        # Save group results
        infer_result.draw_model(os.path.join(local_md_dir, f"{group_name}_model.pdf"))
        pipe_result.draw_layout(os.path.join(local_md_dir, f"{group_name}_layout.pdf"))
        pipe_result.draw_span(os.path.join(local_md_dir, f"{group_name}_spans.pdf"))
        pipe_result.dump_md(md_writer, f"{group_name}.md", image_dir)
        pipe_result.dump_content_list(md_writer, f"{group_name}_content_list.json", image_dir)
        pipe_result.dump_middle_json(md_writer, f'{group_name}_middle.json')
        
        print("Results saved to ", local_md_dir)
        return local_md_dir

def single_task_recognition_group(image_paths, output_dir, MonkeyOCR_model, task, base_folder_path):
    """
    Single task recognition for a group of images
    
    Args:
        image_paths: List of image file paths
        output_dir: Output directory
        MonkeyOCR_model: Pre-initialized model instance
        task: Task type ('text', 'formula', 'table')
        base_folder_path: Base folder path for maintaining relative structure
    """
    print(f"Starting single task recognition: {task} for image group with {len(image_paths)} images")
    
    # Create group name based on first and last image names
    first_name = '.'.join(os.path.basename(image_paths[0]).split(".")[:-1])
    last_name = '.'.join(os.path.basename(image_paths[-1]).split(".")[:-1])
    group_name = f"{first_name}_to_{last_name}_group"
    
    # Maintain relative path structure from base folder
    rel_path = os.path.relpath(os.path.dirname(image_paths[0]), base_folder_path)
    if rel_path == '.':
        local_md_dir = os.path.join(output_dir, group_name)
    else:
        local_md_dir = os.path.join(output_dir, rel_path, group_name)
    
    os.makedirs(local_md_dir, exist_ok=True)
    
    print(f"Output dir: {local_md_dir}")
    md_writer = FileBasedDataWriter(local_md_dir)
    
    # Get task instruction
    instruction = TASK_INSTRUCTIONS.get(task, TASK_INSTRUCTIONS['text'])
    
    # Load all images
    from PIL import Image
    images = []
    for image_path in image_paths:
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file does not exist: {image_path}")
        images.append(Image.open(image_path))
    
    # Start recognition
    print(f"Performing {task} recognition on {len(images)} images...")
    start_time = time.time()
    
    try:
        # Prepare instructions for all images
        instructions = [instruction] * len(images)
        
        # Use chat model for single task recognition with PIL images directly
        responses = MonkeyOCR_model.chat_model.batch_inference(images, instructions)
        
        recognition_time = time.time() - start_time
        print(f"Recognition time: {recognition_time:.2f}s")
        
        # Combine results
        combined_result = responses[0]
        for i, response in enumerate(responses):
            if i > 0:
                combined_result = combined_result + "\n\n" + response
        
        # Save result
        result_filename = f"{group_name}_{task}_result.md"
        md_writer.write(result_filename, combined_result.encode('utf-8'))
        
        print(f"Single task recognition completed!")
        print(f"Task: {task}")
        print(f"Processed {len(images)} images in group")
        print(f"Result saved to: {os.path.join(local_md_dir, result_filename)}")
        
        # Clean up resources
        try:
            time.sleep(0.5)
            for img in images:
                if hasattr(img, 'close'):
                    img.close()
        except Exception as cleanup_error:
            print(f"Warning: Error during cleanup: {cleanup_error}")
        
        return local_md_dir
        
    except Exception as e:
        raise RuntimeError(f"Single task recognition failed: {str(e)}")

def single_task_recognition(input_file, output_dir, MonkeyOCR_model, task):
    """
    Single task recognition for specific content type
    
    Args:
        input_file: Input file path
        output_dir: Output directory
        MonkeyOCR_model: Pre-initialized model instance
        task: Task type ('text', 'formula', 'table')
    """
    print(f"Starting single task recognition: {task}")
    print(f"Processing file: {input_file}")
    
    # Check if input file exists
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file does not exist: {input_file}")
    
    # Get filename
    name_without_suff = '.'.join(os.path.basename(input_file).split(".")[:-1])
    
    # Prepare output directory
    local_md_dir = os.path.join(output_dir, name_without_suff)
    os.makedirs(local_md_dir, exist_ok=True)
    
    print(f"Output dir: {local_md_dir}")
    md_writer = FileBasedDataWriter(local_md_dir)
    
    # Get task instruction
    instruction = TASK_INSTRUCTIONS.get(task, TASK_INSTRUCTIONS['text'])
    
    # Check file type and prepare images
    file_extension = input_file.split(".")[-1].lower()
    images = []
    
    if file_extension == 'pdf':
        print("⚠️  WARNING: PDF input detected for single task recognition.")
        print("⚠️  WARNING: Converting all PDF pages to images for processing.")
        print("⚠️  WARNING: This may take longer and use more resources than image input.")
        print("⚠️  WARNING: Consider using individual images for better performance.")
        
        try:
            # Convert PDF pages to PIL images directly
            print("Converting PDF pages to images...")
            images = convert_from_path(input_file, dpi=150)
            print(f"Converted {len(images)} pages to images")
            
        except Exception as e:
            raise RuntimeError(f"Failed to convert PDF to images: {str(e)}")
            
    elif file_extension in ['jpg', 'jpeg', 'png']:
        # Load single image
        from PIL import Image
        images = [Image.open(input_file)]
    else:
        raise ValueError(f"Single task recognition supports PDF and image files, got: {file_extension}")
    
    # Start recognition
    print(f"Performing {task} recognition on {len(images)} image(s)...")
    start_time = time.time()
    
    try:
        # Prepare instructions for all images
        instructions = [instruction] * len(images)
        
        # Use chat model for single task recognition with PIL images directly
        responses = MonkeyOCR_model.chat_model.batch_inference(images, instructions)
        
        recognition_time = time.time() - start_time
        print(f"Recognition time: {recognition_time:.2f}s")
        
        # Combine results
        combined_result = responses[0]
        for i, response in enumerate(responses):
            if i > 0:
                combined_result = combined_result + "\n\n" + response
        
        # Save result
        result_filename = f"{name_without_suff}_{task}_result.md"
        md_writer.write(result_filename, combined_result.encode('utf-8'))
        
        print(f"Single task recognition completed!")
        print(f"Task: {task}")
        print(f"Processed {len(images)} image(s)")
        print(f"Result saved to: {os.path.join(local_md_dir, result_filename)}")
        
        # Clean up resources
        try:
            # Give some time for async tasks to complete
            time.sleep(0.5)
            
            # Close images if they were opened
            for img in images:
                if hasattr(img, 'close'):
                    img.close()
                    
        except Exception as cleanup_error:
            print(f"Warning: Error during cleanup: {cleanup_error}")
        
        return local_md_dir
        
    except Exception as e:
        raise RuntimeError(f"Single task recognition failed: {str(e)}")

def parse_file(input_file, output_dir, MonkeyOCR_model, split_pages=False):
    """
    Parse PDF or image and save results
    
    Args:
        input_file: Input PDF or image file path
        output_dir: Output directory
        MonkeyOCR_model: Pre-initialized model instance
        split_pages: Whether to split result by pages
    """
    print(f"Starting to parse file: {input_file}")
    
    # Check if input file exists
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file does not exist: {input_file}")
    
    # Get filename
    name_without_suff = '.'.join(os.path.basename(input_file).split(".")[:-1])
    
    # Prepare output directory
    local_image_dir = os.path.join(output_dir, name_without_suff, "images")
    local_md_dir = os.path.join(output_dir, name_without_suff)
    image_dir = os.path.basename(local_image_dir)
    os.makedirs(local_image_dir, exist_ok=True)
    os.makedirs(local_md_dir, exist_ok=True)
    
    print(f"Output dir: {local_md_dir}")
    image_writer = FileBasedDataWriter(local_image_dir)
    md_writer = FileBasedDataWriter(local_md_dir)
    
    # Read file content
    reader = FileBasedDataReader()
    file_bytes = reader.read(input_file)
    
    # Create dataset instance
    file_extension = input_file.split(".")[-1].lower()
    if file_extension == "pdf":
        ds = PymuDocDataset(file_bytes)
    else:
        ds = ImageDataset(file_bytes)
    
    # Start inference
    print("Performing document parsing...")
    start_time = time.time()
    
    infer_result = ds.apply(doc_analyze_llm, MonkeyOCR_model=MonkeyOCR_model, split_pages=split_pages)
    
    parsing_time = time.time() - start_time
    print(f"Parsing time: {parsing_time:.2f}s")

    # Check if infer_result is a list type
    if isinstance(infer_result, list):
        print(f"Processing {len(infer_result)} pages separately...")
        
        # Process each page result separately
        for page_idx, page_infer_result in enumerate(infer_result):
            page_dir_name = f"page_{page_idx}"
            page_local_image_dir = os.path.join(output_dir, name_without_suff, page_dir_name, "images")
            page_local_md_dir = os.path.join(output_dir, name_without_suff, page_dir_name)
            page_image_dir = os.path.basename(page_local_image_dir)
            
            # Create page-specific directories
            os.makedirs(page_local_image_dir, exist_ok=True)
            os.makedirs(page_local_md_dir, exist_ok=True)
            
            # Create page-specific writers
            page_image_writer = FileBasedDataWriter(page_local_image_dir)
            page_md_writer = FileBasedDataWriter(page_local_md_dir)
            
            print(f"Processing page {page_idx} - Output dir: {page_local_md_dir}")
            
            # Pipeline processing for this page
            page_pipe_result = page_infer_result.pipe_ocr_mode(page_image_writer, MonkeyOCR_model=MonkeyOCR_model)
            
            # Save page-specific results
            page_infer_result.draw_model(os.path.join(page_local_md_dir, f"{name_without_suff}_page_{page_idx}_model.pdf"))
            
            page_pipe_result.draw_layout(os.path.join(page_local_md_dir, f"{name_without_suff}_page_{page_idx}_layout.pdf"))

            page_pipe_result.draw_span(os.path.join(page_local_md_dir, f"{name_without_suff}_page_{page_idx}_spans.pdf"))

            page_pipe_result.dump_md(page_md_writer, f"{name_without_suff}_page_{page_idx}.md", page_image_dir)
            
            page_pipe_result.dump_content_list(page_md_writer, f"{name_without_suff}_page_{page_idx}_content_list.json", page_image_dir)

            page_pipe_result.dump_middle_json(page_md_writer, f'{name_without_suff}_page_{page_idx}_middle.json')
        
        print(f"All {len(infer_result)} pages processed and saved in separate subdirectories")
    else:
        print("Processing as single result...")
        
        # Pipeline processing for single result
        pipe_result = infer_result.pipe_ocr_mode(image_writer, MonkeyOCR_model=MonkeyOCR_model)
        
        # Save single result (original logic)
        infer_result.draw_model(os.path.join(local_md_dir, f"{name_without_suff}_model.pdf"))
        
        pipe_result.draw_layout(os.path.join(local_md_dir, f"{name_without_suff}_layout.pdf"))

        pipe_result.draw_span(os.path.join(local_md_dir, f"{name_without_suff}_spans.pdf"))

        pipe_result.dump_md(md_writer, f"{name_without_suff}.md", image_dir)
        
        pipe_result.dump_content_list(md_writer, f"{name_without_suff}_content_list.json", image_dir)

        pipe_result.dump_middle_json(md_writer, f'{name_without_suff}_middle.json')
    
    print("Results saved to ", local_md_dir)
    return local_md_dir


def main():
    parser = argparse.ArgumentParser(
        description="PDF Document Parsing Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage examples:
  python parse.py input.pdf                  # Parse single PDF file
  python parse.py input.pdf -o ./output      # Parse single PDF with custom output dir
  python parse.py /path/to/folder            # Parse all files in folder
  python parse.py /path/to/folder -g 5       # Group every 5 images as MultiImageDataset
  python parse.py /path/to/folder -t text    # Single task recognition for all files in folder
  python parse.py /path/to/folder -t text -g 5  # Single task recognition with image grouping
  python parse.py input.pdf -c model_configs.yaml
  python parse.py image.jpg -t text          # Single task: text recognition
  python parse.py image.jpg -t formula       # Single task: formula recognition  
  python parse.py image.jpg -t table         # Single task: table recognition
  python parse.py document.pdf -t text       # Single task: text recognition from all PDF pages (with warning)
        """
    )
    
    parser.add_argument(
        "input_path",
        help="Input PDF/image file path or folder path"
    )
    
    parser.add_argument(
        "-o", "--output",
        default="./output",
        help="Output directory (default: ./output)"
    )
    
    parser.add_argument(
        "-c", "--config",
        default="model_configs.yaml",
        help="Configuration file path (default: model_configs.yaml)"
    )
    
    parser.add_argument(
        "-t", "--task",
        choices=['text', 'formula', 'table'],
        help="Single task recognition type (text/formula/table). Supports both image and PDF files."
    )

    parser.add_argument(
        "-s", "--split_pages",
        action='store_true',
        help="Split the output of PDF pages into separate ones (default: False)"
    )
    
    parser.add_argument(
        "-g", "--group-size",
        type=int,
        help="Number of images to group together as MultiImageDataset when processing folders (only applies to image files)"
    )
    
    args = parser.parse_args()
    
    MonkeyOCR_model = None
    
    try:
        # Check if input path is a directory or file
        if os.path.isdir(args.input_path):
            # Process folder
            result_dir = parse_folder(
                args.input_path,
                args.output,
                args.config,
                args.task,
                args.group_size
            )
            
            if args.task:
                if args.group_size:
                    print(f"\n✅ Folder processing with single task ({args.task}) recognition and image grouping (size: {args.group_size}) completed! Results saved in: {result_dir}")
                else:
                    print(f"\n✅ Folder processing with single task ({args.task}) recognition completed! Results saved in: {result_dir}")
            else:
                if args.group_size:
                    print(f"\n✅ Folder processing with image grouping (size: {args.group_size}) completed! Results saved in: {result_dir}")
                else:
                    print(f"\n✅ Folder processing completed! Results saved in: {result_dir}")
        elif os.path.isfile(args.input_path):
            # Process single file - initialize model for single file processing
            print("Loading model...")
            MonkeyOCR_model = MonkeyOCR(args.config)
            
            if args.task:
                result_dir = single_task_recognition(
                    args.input_path,
                    args.output,
                    MonkeyOCR_model,
                    args.task
                )
                print(f"\n✅ Single task ({args.task}) recognition completed! Results saved in: {result_dir}")
            else:
                result_dir = parse_file(
                    args.input_path,
                    args.output,
                    MonkeyOCR_model,
                    args.split_pages
                )
                print(f"\n✅ Parsing completed! Results saved in: {result_dir}")
        else:
            raise FileNotFoundError(f"Input path does not exist: {args.input_path}")
            
    except Exception as e:
        print(f"\n❌ Processing failed: {str(e)}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Clean up resources
        try:
            if MonkeyOCR_model is not None:
                # Clean up model resources if needed
                if hasattr(MonkeyOCR_model, 'chat_model') and hasattr(MonkeyOCR_model.chat_model, 'close'):
                    MonkeyOCR_model.chat_model.close()
                    
            # Give time for async tasks to complete before exiting
            time.sleep(1.0)
            
            if dist.is_initialized():
                dist.destroy_process_group()
                
        except Exception as cleanup_error:
            print(f"Warning: Error during final cleanup: {cleanup_error}")


if __name__ == "__main__":
    main()