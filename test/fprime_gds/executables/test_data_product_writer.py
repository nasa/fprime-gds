import unittest
import os
import sys

from fprime_gds.executables import data_product_writer

class TestRunDataProduct(unittest.TestCase):

    def test_data_product_parser(self):
        args = data_product_writer.parse_args(["test.bin", "dictionary.json"])
        assert args.binFile == "test.bin"
        assert args.jsonDict == "dictionary.json"

    def test_data_product_writer(self):
        # Specify the directory where the .bin files are located
        directory = os.path.abspath(os.path.dirname(__file__))
        # Loop through each file in the specified directory
        for filename in os.listdir(directory):
            # Check if the file is a .bin file
            if filename.endswith(".bin"):
                bin_file = os.path.join(directory, filename)
                dict_file = os.path.join(directory, "dictionary.json")
                args = data_product_writer.parse_args([bin_file, dict_file])
                data_product_writer.process(args)
                return
                

