import unittest
import os

from fprime_gds.executables import data_product_writer

class TestRunDataProduct(unittest.TestCase):

    def test_data_product_parser(self):
        args = data_product_writer.parse_args(["test.bin", "dictionary.json"])
        assert args.binFile == "test.bin"
        assert args.jsonDict == "dictionary.json"

    def test_data_product_writer(self):
        binFiles = ["makeBool.bin",
                    "makeDataArray.bin",
                    "makeF32.bin",
                    "makeFppArray.bin",
                    "makeI32.bin",
                    "makeI8.bin",
                    "makeU32Array.bin",
                    "makeComplex.bin",
                    "makeEnum.bin",
                    "makeF64.bin",
                    "makeI16.bin",
                    "makeI64.bin",
                    "makeU32.bin",
                    "makeU8Array.bin"]
        
        # Specify the directory where the .bin files are located
        cwd_directory = os.getcwd()
        test_directory = os.path.dirname(os.path.abspath(__file__))

        # Loop through each file in the specified directory
        for filename in binFiles:
            print(f'Processing {filename}')
            bin_file = os.path.join(test_directory, "dp_writer_data", filename)
            dict_file = os.path.join(test_directory, "dp_writer_data", "dictionary.json")
            args = data_product_writer.parse_args([bin_file, dict_file])
            data_product_writer.DataProductWriter(args.jsonDict, args.binFile).process()
            #data_product_writer.process(args)

            # Check if the json file was created
            jsonFile = filename.replace('.bin', '.json')
            jsonFilePath = os.path.join(cwd_directory, jsonFile)
            self.assertTrue(os.path.exists(jsonFilePath))
    
            # If the json file exists, delete it
            if os.path.exists(jsonFilePath):
                    os.remove(jsonFile)