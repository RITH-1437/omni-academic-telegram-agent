import io
import json
import unittest
import openpyxl

from services.document_parser import document_parser


class TestDocumentExpansion(unittest.TestCase):
    def test_excel_parsing(self):
        # Create an in-memory workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "StudentGrades"
        ws.append(["Student ID", "Name", "Course", "Score"])
        ws.append(["101", "Alice", "Artificial Intelligence", 95.5])
        ws.append(["102", "Bob", "Cloud Computing", 88.0])

        stream = io.BytesIO()
        wb.save(stream)
        excel_bytes = stream.getvalue()

        extracted, meta = document_parser.extract_text(excel_bytes, "grades.xlsx")
        self.assertEqual(meta["type"], "Excel Spreadsheet")
        self.assertIn("StudentGrades", meta["sheet_names"])
        self.assertIn("Student ID | Name | Course | Score", extracted)
        self.assertIn("101 | Alice | Artificial Intelligence | 95.5", extracted)

    def test_jupyter_notebook_parsing(self):
        # Create an in-memory Jupyter Notebook JSON
        nb = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": ["# Lab 1: Image Convolution\n", "Implement 3x3 Sobel filter.\n"],
                },
                {
                    "cell_type": "code",
                    "source": ["import cv2\n", "img = cv2.imread('test.png')\n", "sobel = cv2.Sobel(img, cv2.CV_64F, 1, 0)\n"],
                    "outputs": [
                        {
                            "output_type": "error",
                            "ename": "FileNotFoundError",
                            "evalue": "test.png not found",
                            "traceback": ["Traceback (most recent call last):\n", "FileNotFoundError: test.png not found\n"],
                        }
                    ],
                },
            ]
        }
        nb_bytes = json.dumps(nb).encode("utf-8")
        extracted, meta = document_parser.extract_text(nb_bytes, "cv_lab1.ipynb")
        self.assertEqual(meta["type"], "Jupyter Notebook")
        self.assertEqual(meta["code_cells"], 1)
        self.assertEqual(meta["markdown_cells"], 1)
        self.assertIn("Lab 1: Image Convolution", extracted)
        self.assertIn("cv2.Sobel", extracted)
        self.assertIn("FileNotFoundError: test.png not found", extracted)

    def test_csv_parsing(self):
        csv_data = b"Dataset,Instances,Features,Target\nIris,150,4,Species\nMNIST,70000,784,Digit\n"
        extracted, meta = document_parser.extract_text(csv_data, "datasets.csv")
        self.assertEqual(meta["type"], "Tabular (CSV/TSV)")
        self.assertIn("Iris | 150 | 4 | Species", extracted)

    def test_tsv_parsing(self):
        tsv_data = b"Token\tPOS\tLabel\nApple\tNNP\tB-ORG\nreleases\tVBZ\tO\n"
        extracted, meta = document_parser.extract_text(tsv_data, "ner.tsv")
        self.assertEqual(meta["type"], "Tabular (CSV/TSV)")
        self.assertIn("Apple | NNP | B-ORG", extracted)

    def test_markup_parsing(self):
        html_data = b"<html><body><h1>Lecture 5: TLS 1.3</h1><p>The TLS handshake uses ECDHE.</p></body></html>"
        extracted, meta = document_parser.extract_text(html_data, "lecture.html")
        self.assertEqual(meta["type"], "Markup (HTML/XML)")
        self.assertIn("Lecture 5: TLS 1.3", extracted)
        self.assertIn("The TLS handshake uses ECDHE.", extracted)

    def test_source_code_parsing(self):
        code_data = b"def bellman_equation(v_s, gamma, reward):\n    return reward + gamma * max(v_s)\n"
        extracted, meta = document_parser.extract_text(code_data, "mdp.py")
        self.assertIn("Source/Text (.py)", meta["type"])
        self.assertIn("def bellman_equation", extracted)


if __name__ == "__main__":
    unittest.main()
