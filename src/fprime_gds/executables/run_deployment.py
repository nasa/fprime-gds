####
# run_deployment.py:
#
# Runs a deployment. Starts a GUI, a TCPServer, and the deployment application.
####
import os
import sys
import copy
import pathlib
import webbrowser

from fprime_gds.executables.cli import (
    BinaryDeployment,
    ConfigDrivenParser,
    CompositeParser,
    CommParser,
    GdsParser,
    ParserBase,
    StandardPipelineParser,
    PluginArgumentParser,
)
from fprime_gds.executables.utils import AppWrapperException, run_wrapped_application
from fprime_gds.plugin.system import Plugins

BASE_MODULE_ARGUMENTS = [sys.executable, "-u", "-m"]


def parse_args():
    """Parse command line arguments
    Gets an argument parsers to read the command line and process the arguments. Return
    the arguments in their namespace.

    :return: parsed argument namespace
    """
    # Get custom handlers for all executables we are running
    arg_handlers = [
        StandardPipelineParser,
        GdsParser,
        BinaryDeployment,
        CommParser,
        PluginArgumentParser,
    ]
    # If the FPRIME_GDS_CONFIG_PATH environment variable is set, set its value to be the default
    # config path
    if "FPRIME_GDS_CONFIG_PATH" in os.environ:
        ConfigDrivenParser.set_default_configuration(
            pathlib.Path(os.environ["FPRIME_GDS_CONFIG_PATH"])
        )
    # Parse the arguments, and refine through all handlers
    args, parser = ConfigDrivenParser.parse_args(
        arg_handlers, "Run F prime deployment and GDS"
    )
    return args


def launch_process(cmd, logfile=None, name=None, env=None, launch_time=5):
    """
    Launch a child subprocess. This subprocess will allow the child to run outside of the memory context of Python.

    :param cmd: list of command arguments to run by handing to subprocess.
    :param logfile: (optional) place to redirect output to for purposes of logging. Default: None, screen.
    :param name: (optional) short name for printing messages.
    :param env: (optional) environment to run in. Allows for special environment contexts.
    :param launch_time: (optional) time to launch the process, before rendering an error.
    :return: running process
    """
    if name is None:
        name = str(cmd)
    print(f"[INFO] Ensuring {name} is stable for at least {launch_time} seconds")
    try:
        return run_wrapped_application(cmd, logfile, env, launch_time)
    except AppWrapperException as awe:
        print(f"[ERROR] {str(awe)}.", file=sys.stderr)
        try:
            if logfile is not None:
                with open(logfile) as file_handle:
                    for line in file_handle:
                        print(f"    [LOG] {line.strip()}", file=sys.stderr)
        except Exception:
            pass
        msg = f"Failed to run {name}"
        raise AppWrapperException(msg)


def launch_tts(parsed_args):
    """Launch the ThreadedTcpServer middleware application


    Args:
        parsed_args: parsed argument namespace
    Return:
        launched process
    """
    # Open log, and prepare to close it cleanly on exit
    tts_log = os.path.join(parsed_args.logs, "ThreadedTCP.log")
    # Launch the tcp server
    tts_cmd = BASE_MODULE_ARGUMENTS + [
        "fprime_gds.executables.tcpserver",
        "--port",
        str(parsed_args.tts_port),
        "--host",
        str(parsed_args.tts_addr),
    ]
    return launch_process(tts_cmd, logfile=tts_log, name="TCP Server")


def launch_html(parsed_args):
    """Launch the Flask application

    Args:
        parsed_args: parsed argument namespace
    Return:
        launched process
    """
    composite_parser = CompositeParser([StandardPipelineParser, ConfigDrivenParser])
    reproduced_arguments = StandardPipelineParser().reproduce_cli_args(parsed_args)
    if "--log-directly" not in reproduced_arguments:
        reproduced_arguments += ["--log-directly"]
    flask_env = os.environ.copy()
    flask_env.update(
        {
            "FLASK_APP": "fprime_gds.flask.app",
            "STANDARD_PIPELINE_ARGUMENTS": "|".join(reproduced_arguments),
            "SERVE_LOGS": "YES",
        }
    )
    gse_args = BASE_MODULE_ARGUMENTS + [
        "flask",
        "run",
        "--host",
        str(parsed_args.gui_addr),
        "--port",
        str(parsed_args.gui_port),
    ]
    ret = launch_process(gse_args, name="HTML GUI", env=flask_env, launch_time=2)
    ui_url = f"http://{str(parsed_args.gui_addr)}:{str(parsed_args.gui_port)}/"
    print(f"[INFO] Launched UI at: {ui_url}")
    webbrowser.open(
        ui_url,
        new=0,
        autoraise=True,
    )
    return ret


def launch_app(parsed_args):
    """Launch the raw application

    Args:
        parsed_args: parsed argument namespace
    Return:
        launched process
    """
    app_path = parsed_args.app
    logfile = os.path.join(parsed_args.logs, f"{app_path.name}.log")
    app_cmd = [
        app_path.absolute(),
        "-p",
        str(parsed_args.port),
        "-a",
        parsed_args.address,
    ]
    return launch_process(
        app_cmd, name=f"{app_path.name} Application", logfile=logfile, launch_time=1
    )


def launch_comm(parsed_args):
    """Launch the communication adapter process

    Args:
        parsed_args: parsed argument namespace
    Return:
        launched process
    """
    arguments = CommParser().reproduce_cli_args(parsed_args)
    arguments = (
        arguments + ["--log-directly"]
        if "--log-directly" not in arguments
        else arguments
    )
    app_cmd = BASE_MODULE_ARGUMENTS + ["fprime_gds.executables.comm"] + arguments
    return launch_process(
        app_cmd,
        name=f"comm[{parsed_args.communication_selection}] Application",
        launch_time=1,
    )


def launch_plugin(parsed_args, plugin_class_instance):
    """Launch a plugin instance"""
    plugin_name = getattr(
        plugin_class_instance,
        "get_name",
        lambda: plugin_class_instance.__class__.__name__,
    )()
    plugin_args = copy.deepcopy(parsed_args)
    # Set logging to use a subdirectory within the root logs directory
    plugin_logs = os.path.join(plugin_args.logs, plugin_name)
    os.mkdir(plugin_logs)
    plugin_args.logs = plugin_logs
    plugin_args.log_directly = True
    return launch_process(
        plugin_class_instance.get_process_invocation(plugin_args),
        name=f"{ plugin_name } Plugin App",
        launch_time=1,
    )


def main():
    """
    Main function used to launch processes.
    """
    parsed_args = parse_args()
    launchers = []

    # Launch middleware layer if not using ZMQ
    if not parsed_args.zmq:
        launchers.append(launch_tts)

    # Check if we are running with communications
    if parsed_args.communication_selection != "none":
        launchers.append(launch_comm)

    # Add app, if possible
    if parsed_args.app:
        if parsed_args.communication_selection == "ip":
            launchers.append(launch_app)
        else:
            print(
                "[WARNING] App cannot be auto-launched without IP adapter",
                file=sys.stderr,
            )

    # Launch the desired GUI package
    if parsed_args.gui == "html":
        launchers.append(launch_html)

    # Launch launchers and wait for the last app to finish
    try:
        procs = [launcher(parsed_args) for launcher in launchers]
        _ = [
            launch_plugin(parsed_args, cls(namespace=parsed_args))
            for cls in Plugins.system().get_feature_classes("gds_app")
        ]
        _ = [
            instance().run(parsed_args)
            for instance in Plugins.system().get_feature_classes("gds_function")
        ]

        print("[INFO] F prime is now running. CTRL-C to shutdown all components.")
        procs[-1].wait()
    except KeyboardInterrupt:
        print("[INFO] CTRL-C received. Exiting.")
    except Exception as exc:
        print(f"[INFO] Shutting down F prime due to error. {str(exc)}", file=sys.stderr)
        return 1
    # Processes are killed atexit
    return 0


if __name__ == "__main__":
    sys.exit(main())
