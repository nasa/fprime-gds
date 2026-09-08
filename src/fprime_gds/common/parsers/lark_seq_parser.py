import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator, List, Optional, Tuple, Union

from lark import Lark, Transformer, Token, Tree
from lark.exceptions import LarkError, UnexpectedCharacters, UnexpectedToken

from fprime_gds.common.data_types import exceptions as gseExceptions
from fprime_gds.common.models.common.command import Descriptor


class JsonArgument(str):
    """JSON-encoded array/object argument, distinguishable from a plain string literal."""

    @classmethod
    def encode(cls, value: Union[list, dict]) -> "JsonArgument":
        return cls(json.dumps(value))

    def decode(self) -> Any:
        return json.loads(self)


def _nested_value(item: Any) -> Any:
    """Decode nested arrays/objects so they embed as structures rather than strings."""
    return item.decode() if isinstance(item, JsonArgument) else item


class SeqTransformer(Transformer[Token, Any]):
    """Transform the Lark parse tree into Python objects."""

    def number(self, items: List[Token]) -> Union[int, float]:
        """Convert number tokens to int or float."""
        token = items[0]
        assert isinstance(token, Token)
        if token.type == "FLOAT_NUMBER":
            return float(token.value)
        elif token.type == "HEX_NUMBER":
            return int(token.value, 16)
        else:  # DEC_NUMBER
            return int(token.value)

    def string(self, items: List[Token]) -> str:
        """Remove quotes from string literals."""
        token = items[0]
        assert isinstance(token, Token)
        value = token.value
        # Remove surrounding quotes
        return value[1:-1]

    def boolean(self, items: List[Token]) -> bool:
        """Convert boolean tokens to Python bool."""
        token = items[0]
        assert isinstance(token, Token)
        return token.type == "CONST_TRUE"

    def mnemonic(self, items: List[Token]) -> str:
        """Extract mnemonic name."""
        token = items[0]
        assert isinstance(token, Token)
        return token.value

    def value(self, items: List[Any]) -> Any:
        """Return the parsed argument value."""
        item = items[0]
        # Handle NAME tokens (enum values, identifiers)
        if isinstance(item, Token) and item.type == "NAME":
            return item.value
        return item

    def array(self, items: List[Any]) -> JsonArgument:
        """Convert array items to JSON string for serialization layer."""
        # None entries come from optional groups in the grammar
        return JsonArgument.encode(
            [_nested_value(item) for item in items if item is not None]
        )

    def kv(self, items: List[Any]) -> Tuple[str, Any]:
        """Convert key-value pair to tuple (key, value)."""
        key = items[0]
        value = items[1]
        assert isinstance(key, Token) and key.type == "NAME"
        return (key.value, value)

    def object(self, items: List[Optional[Tuple[str, Any]]]) -> JsonArgument:
        """Convert key-value pairs to JSON string for serialization layer."""
        # None entries come from optional groups in the grammar
        return JsonArgument.encode(
            {key: _nested_value(value) for key, value in (item for item in items if item is not None)}
        )


class LarkSeqFileParser:
    """Lark-based parser for F' sequence files."""

    def __init__(self):
        """Initialize the parser with the grammar file."""
        grammar_path = Path(__file__).parent / "grammar.lark"
        with open(grammar_path) as f:
            self.parser = Lark(f.read(), start="input", parser="lalr")
        self.transformer = SeqTransformer()

    def parse(self, filename: str, cont: bool = False) -> Generator[Tuple[int, Descriptor, int, int, str, List[Any]], None, None]:
        """
        Generator that parses an input sequence file and returns a tuple
        for each valid line of the sequence file.

        @param filename: A sequence file name (usually a .seq extension)
        @param cont: attempt to continue after a line fails to parse, hopefully revealing more errors
        @return A generator of tuples:
            (lineNumber, descriptor, seconds, useconds, mnemonic, arguments)
        """
        filename_abs = Path(filename).absolute()

        with open(filename) as f:
            content = f.read()

        try:
            tree = self.parser.parse(content)
        except (UnexpectedCharacters, UnexpectedToken) as e:
            # Extract line number from Lark error
            line_num = e.line
            col_num = e.column
            msg = f"{filename_abs}:{line_num}:{col_num}: Encountered syntax error parsing"
            if isinstance(e, UnexpectedToken):
                t_name = repr(e.token)
                msg += f": unexpected token '{t_name}'"
            raise gseExceptions.GseControllerParsingException(msg)
        except LarkError as e:
            # Generic Lark error
            msg = f"{filename_abs}:1: Encountered syntax error parsing sequence file"
            raise gseExceptions.GseControllerParsingException(msg)

        messages: List[str] = []

        # Parse the flattened tree structure
        # Pattern: time_tag, mnemonic, [argument, argument, ...], time_tag, mnemonic, ...
        i = 0
        children = tree.children
        assert isinstance(children, list)

        while i < len(children):
            time_tag = None
            line_number = 0

            try:
                # Find time_tag
                if not (
                    hasattr(children[i], "data") and children[i].data == "time_tag"
                ):
                    i += 1
                    continue

                time_tag_node = children[i]
                assert isinstance(time_tag_node, Tree)
                time_tag = time_tag_node
                i += 1

                # Next should be mnemonic
                if i >= len(children) or not (
                    hasattr(children[i], "data") and children[i].data == "mnemonic"
                ):
                    i += 1
                    continue

                mnemonic_node = children[i]
                assert isinstance(mnemonic_node, Tree)
                i += 1

                # Collect arguments until we hit another time_tag or end
                arguments: List[Tree[Token]] = []
                while (
                    i < len(children)
                    and hasattr(children[i], "data")
                    and children[i].data == "value"
                ):
                    arg_node = children[i]
                    assert isinstance(arg_node, Tree)
                    arguments.append(arg_node)
                    i += 1

                # Transform the nodes
                mnemonic_result = self.transformer.transform(mnemonic_node)
                assert isinstance(mnemonic_result, str)
                mnemonic = mnemonic_result
                parsed_args = []
                for arg in arguments:
                    assert isinstance(arg, Tree)
                    parsed_args.append(self.transformer.transform(arg))

                # Get the actual line number from the time tag token's metadata
                # Navigate to the first token to get line info
                first_token = self._get_first_token(time_tag)
                line_number = (
                    first_token.line - 1 if hasattr(first_token, "line") else 0
                )

                # Parse the time tag
                descriptor, seconds, useconds = self._parse_time_tag(
                    time_tag, line_number
                )

                yield line_number, descriptor, seconds, useconds, mnemonic, parsed_args

            except gseExceptions.GseControllerParsingException as exc:
                # Re-raise GseControllerParsingException as-is
                if not cont:
                    raise
                messages.append(str(exc))
                i += 1
            except Exception as exc:
                # Wrap other exceptions with line number
                if not cont:
                    msg = f"{filename_abs}:{line_number + 1}: Encountered syntax error parsing timestamp: {exc}"
                    raise gseExceptions.GseControllerParsingException(msg)
                messages.append(f"{filename_abs}:{line_number + 1}: {exc}")
                i += 1

        if cont and messages:
            raise gseExceptions.GseControllerParsingException("\n".join(messages))

    def _parse_time_tag(self, time_tag: Tree[Token], line_number: int) -> Tuple[Descriptor, int, int]:
        """
        Parse a time tag and return descriptor, seconds, and useconds.

        @param time_tag: The time_tag parse tree node
        @param line_number: Current line number for error reporting
        @return: Tuple of (descriptor, seconds, useconds)
        """
        time_token = time_tag.children[0]
        assert isinstance(time_token, Token)
        # Strip the leading 'R' / 'A' descriptor character
        time_str = time_token.value[1:]

        if time_token.type == "RELATIVE_TIME":
            descriptor = Descriptor.RELATIVE
            dt = self._parse_time_string(time_str)
            delta = timedelta(
                hours=dt.hour,
                minutes=dt.minute,
                seconds=dt.second,
                microseconds=dt.microsecond,
            ).total_seconds()

        elif time_token.type == "ABSOLUTE_TIME":
            descriptor = Descriptor.ABSOLUTE
            dt = self._parse_datetime_string(time_str)

            # Use UTC timezone
            if dt.tzinfo is not None:
                epoch = datetime.fromtimestamp(0, dt.tzinfo)
            else:
                epoch = datetime.utcfromtimestamp(0)
            delta = (dt - epoch).total_seconds()

        else:
            msg = f"Line {line_number + 1}: Invalid time descriptor found"
            raise gseExceptions.GseControllerParsingException(msg)

        seconds = int(delta)
        useconds = int((delta - seconds) * 1000000)
        return descriptor, seconds, useconds

    def _parse_time_string(self, time_str: str) -> datetime:
        """
        Parse a relative time string (HH:MM:SS or HH:MM:SS.ffffff).

        @param time_str: Time string to parse
        @return: datetime object with the parsed time
        """
        if "." in time_str:
            return datetime.strptime(time_str, "%H:%M:%S.%f")
        else:
            return datetime.strptime(time_str, "%H:%M:%S")

    def _parse_datetime_string(self, datetime_str: str) -> datetime:
        """
        Parse an absolute datetime string (YYYY-DDDTHH:MM:SS or YYYY-DDDTHH:MM:SS.ffffff).

        @param datetime_str: DateTime string to parse
        @return: datetime object with the parsed datetime
        """
        if "." in datetime_str:
            return datetime.strptime(datetime_str, "%Y-%jT%H:%M:%S.%f")
        else:
            return datetime.strptime(datetime_str, "%Y-%jT%H:%M:%S")

    def _get_first_token(self, tree: Union[Tree[Token], Token]) -> Optional[Token]:
        """
        Recursively get the first token from a parse tree.

        @param tree: A Tree or Token object
        @return: The first Token in the tree
        """
        if isinstance(tree, Token):
            return tree
        if hasattr(tree, "children") and tree.children:
            return self._get_first_token(tree.children[0])
        return None
