#!/usr/bin/env python3

import traceback
import time
import os

from fabric.api import *

from common import *
# This is expected to be launch from the ci container
from ci_variables import *

def initialize_manager(max_runtime):
    """ Performs the prerequisite tasks for all CI jobs that will run on the manager instance

    max_runtime (hours): The maximum uptime this manager and its associated
        instances should have before it is stopped. This serves as a redundant check
        in case the workflow-monitor is brought down for some reason.
    """

    # Catch any exception that occurs so that we can gracefully teardown
    try:
        # wait until machine launch is complete
        with cd(manager_home_dir):
            # add firesim.pem
            with open(manager_fsim_pem, "w") as pem_file:
                pem_file.write(os.environ["FIRESIM_PEM"])
            os.chmod(manager_fsim_pem, 600)
            set_fabric_firesim_pem()

            run("git clone https://github.com/firesim/firesim.git")

        with cd(manager_fsim_dir):
            run("git checkout " + ci_commit_sha1)
            run("./build-setup.sh --fast")

        # Initialize marshal submodules early because it appears some form of
        # contention between submodule initialization and the jgit SBT plugin
        # causes SBT to lock up, causing downstream scala tests to fail when
        # run concurrently with ./init-submodules.sh
        with cd(manager_marshal_dir):
            run("./init-submodules.sh")

        with cd(manager_fsim_dir), prefix("source ./sourceme-f1-manager.sh"):
            run(".github/scripts/firesim-managerinit.expect {} {} {}".format(
                os.environ["AWS_ACCESS_KEY_ID"],
                os.environ["AWS_SECRET_ACCESS_KEY"],
                os.environ["AWS_DEFAULT_REGION"]))

        with cd(manager_ci_dir):
            # Put a baseline time-to-live bound on the manager.
            # Instances will be stopped and cleaned up in a nightly job.

            # Setting pty=False is required to stop the screen from being
            # culled when the SSH session associated with teh run command ends.
            run("screen -S ttl -dm bash -c \'sleep {}; ./change-workflow-instance-states.py {} stop {}\'"
                .format(int(max_runtime) * 3600, ci_workflow_id, ci_personal_api_token), pty=False)
            run("screen -S workflow-monitor -L -dm ./workflow-monitor.py {} {} {}"
                .format(ci_workflow_id, ci_api_token, ci_personal_api_token), pty=False)

    except BaseException as e:
        traceback.print_exc(file=sys.stdout)
        terminate_workflow_instances(ci_workflow_id)
        sys.exit(1)

if __name__ == "__main__":
    max_runtime = sys.argv[1]
    execute(initialize_manager, max_runtime, hosts=["localhost"])
