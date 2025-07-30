"""
__init__.py:

Python Logging Setup. This sets up the global logging format for all Gds components. This allows the user to use Python
loggers without calling basic config.

@author mstarch
"""
import logging
import os
import sys

INITIALIZED = False


def configure_py_log(directory=None, filename=sys.argv[0], mirror_to_stdout=False, log_level="INFO"):
    """
    Configure the python logging. If logdir is supplied, our logs will go in that directory as a log file. Otherwise,
    logs will go to the CLI.

    :param directory: directory logs are written into
    :param filename: logging filename
    :param mode: of file to write
    :param mirror_to_stdout: mirror the log output to standard our
    """
    global INITIALIZED
    if INITIALIZED:
        return
    handlers = (
        [logging.StreamHandler(sys.stdout)]
        if directory is None or mirror_to_stdout
        else []
    )
    if directory is not None:
        log_file = os.path.join(directory, os.path.basename(filename))
        log_file = log_file if log_file.endswith(".log") else f"{log_file}.log"
        handlers.append(logging.FileHandler(log_file))
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s")

    for handler in handlers:
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(log_level)
    logging.info("Logging system initialized!")
    INITIALIZED = True
