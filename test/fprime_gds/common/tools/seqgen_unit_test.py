import filecmp
from pathlib import Path
import tempfile
import unittest

import fprime_gds.common.tools.seqgen as seqgen

class APITestCases(unittest.TestCase):
    def test_nominal_sequence(self):
        self.assertEqual(self.diff_input_sequence(
            "./input/simple_sequence.seq",
            "./expected/simple_sequence_expected.bin",
            "./resources/simple_dictionary.json"
        ), True)
    
    # This test is expected to fail due to unmatched command in
    # simple_bad_sequence.seq and seqgen should produce a SeqGenException. 
    # Passing these executions is a test failure.
    @unittest.expectedFailure 
    def test_fail_unmatched_command_sequence(self):
        self.diff_input_sequence(
            "./input/simple_bad_sequence.seq",
            "./expected/simple_sequence_expected.bin",
            "./resources/simple_dictionary.json"
        )
        
    def diff_input_sequence(self, input_sequence, expected_output, dictionary):
        temp_dir = tempfile.TemporaryDirectory()
        output_bin = Path(f"{temp_dir.name}/out_binary")
        seqgen.generateSequence(
            input_sequence,
            output_bin,
            dictionary,
            0xffff
        )
        is_equal = filecmp.cmp(output_bin, expected_output)
        temp_dir.cleanup()
        return is_equal
        
    
if __name__ == "__main__":
    unittest.main()