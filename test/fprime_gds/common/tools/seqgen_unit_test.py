import filecmp
from pathlib import Path
import tempfile
import unittest

import fprime_gds.common.tools.seqgen as seqgen

class APITestCases(unittest.TestCase):
    def test_nominal_sequence(self):
        self.assertEqual(self.check_sequence_generates_expected_binary(
            Path(__file__).parent / "input" / "simple_sequence.seq",
            Path(__file__).parent / "expected" / "simple_expected.bin",
            Path(__file__).parent / "resources" / "simple_dictionary.json"
        ), True)
    
    def test_fail_unmatched_command_sequence(self):
        with self.assertRaisesRegex(seqgen.SeqGenException, "does not match any command in the command dictionary."):
            self.check_sequence_generates_expected_binary(
                Path(__file__).parent / "input" / "simple_bad_sequence.seq",
                Path(__file__).parent / "expected" / "simple_expected.bin",
                Path(__file__).parent / "resources" / "simple_dictionary.json"
            )
        
    def check_sequence_generates_expected_binary(self, 
                                                 input_sequence, 
                                                 expected_binary, 
                                                 dictionary):
        temp_dir = tempfile.TemporaryDirectory()
        output_bin = Path(f"{temp_dir.name}/out_binary")
        seqgen.generateSequence(
            input_sequence,
            output_bin,
            dictionary,
            0xffff
        )
        is_equal = filecmp.cmp(output_bin, expected_binary)
        temp_dir.cleanup()
        return is_equal
        
    
if __name__ == "__main__":
    unittest.main()