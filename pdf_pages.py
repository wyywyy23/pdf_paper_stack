from pdf2image import convert_from_path
import sys
import os


def pdf_to_images(pdf_path, output_folder):
    images = convert_from_path(pdf_path, dpi=600)
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    for i, image in enumerate(images):
        image.save(f"{output_folder}/page_{i}.jpg", "JPEG")


def main(pdf_path, output_folder):
    pdf_to_images(pdf_path, f"img/{output_folder}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
