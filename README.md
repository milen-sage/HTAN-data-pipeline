# HTAN Data Ingress Pipeline

## Usage

### Virtual Environment Setup

Python 3 has built-in support for virtual environments (using `venv` module). Perform the following steps:

_Note: It is assumed that you are running all the below commands from the main/root (`HTAN-data-pipeline`) directory._

After cloning the git repository, navigate into the `HTAN-data-pipeline` directory and run the command as below:

```bash
python[3] -m venv .venv
```

This creates a Python3 virtual environment (within the `root` folder/package), with its own site directories (isolated from the system site directories).

To activate the virtual environment, run:

```bash
source .venv/bin/activate
```

_Note: You should now see the name of the virtual environment to the left of the prompt._

### Install App/Package

To install the package/bundle/application:

```bash
pip[3] install -e .
```

To verify that the package has been installed (as a `pip` package), check here:

```bash
pip[3] list
```

Now, your environment is ready to test the modules within the application.

Once, you have finished testing the application within the virtual environment and want to deactivate it, simply run:

```bash
deactivate
```

To run any of the example file(s), go to your root directory and execute/run python script in the following way:

Let's say you want to run the `metadata_usage` example - then do this:

```bash
python[3] ingresspipe/models/examples/metadata_usage.py
```

----

### Contribution

Clone a copy of the repository here:
      
```bash
git clone --single-branch --branch <branch> https://github.com/milen-sage/HTAN-data-pipeline.git
```

Modify your files, add them to the staging area, use a descriptive commit message and push to the same branch as a pull request for review.

* Please consult [CONTRIBUTION.md](https://github.com/milen-sage/HTAN-data-pipeline/blob/<branch>/CONTRIBUTION.md) for further reference.
