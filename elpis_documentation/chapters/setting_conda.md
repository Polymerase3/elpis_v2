
# Managing Your Conda Environment

Using a Conda environment is essential for any project that requires consistent and reproducible software dependencies. It ensures your project runs with the exact package versions and settings you specify, avoiding the infamous “it works on my machine” dilemma. Proper environment management is especially critical for scaling, deploying on servers, or using containers like Docker.

---

#  Step 1: Creating a Project Folder and Conda Environment

Begin by setting up a dedicated directory for your project and initializing a new Conda environment:

```bash
mkdir ~/elpis2
cd ~/elpis2
conda create --no-default-packages --name elpis_v2 python=3.13.2 r-essentials r-base=4.3.1 postgresql=17.4
```

You can also create an environment from a predefined `environment.yml` file:

```bash
conda env create -f environment.yml
```

---

## 📄 Creating and Using a Spec File

Conda can generate a **spec file** containing an exact list of package versions and build strings, making your environment fully reproducible.

### 🔧 Create a Spec File

```bash
conda list --explicit > spec-file.txt
```

### 🛠️ Create Environment from Spec File

```bash
conda create --name myenv --file spec-file.txt
```

### 📦 Install Packages from Spec File into Existing Environment

```bash
conda install --name myenv --file spec-file.txt
```

---

## ⚙️ Activating and Managing Environments

### ▶️ Activate an Environment

Once created, activate your environment:

```bash
conda activate elpis_v2
```

### ❌ Deactivate and Delete Environment

When you no longer need the environment:

```bash
conda deactivate 
conda remove -n ENV_NAME --all
```

---

#  Step 2: Logging the Environment

Documenting your environment is critical for collaboration and reproducibility.

## 📤 Export Environment to YAML

To export all dependencies (including pip-installed packages) to a human-readable YAML file:

```bash
conda env export > environment_setup.yml
```

This file can be shared to recreate the environment using `conda env create -f environment_setup.yml`.

## 🔍 Export an Explicit Spec File

For a byte-for-byte identical reproduction, use:

```bash
conda list --explicit > spec-file.txt
```

This includes build info and channels but is not human-readable.

---

## ✅ Best Practices

- Keep both `environment.yml` and `spec-file.txt` under version control (e.g., in Git).
- Use `environment.yml` for collaboration and readability.
- Use `spec-file.txt` for precise replication on the same system.
- Regularly export and update these files as your environment evolves.

Maintainable environments save time and frustration—invest in managing them well. 💡

---

# Step 3: Managing Packages in Conda Environments

Managing packages is a crucial step in maintaining a clean and efficient conda environment. This guide walks you through listing, searching, installing, and updating packages using `conda`, `conda-forge`, and `pip`.

---

## 📦 Listing Installed Packages

To view all packages installed in a specific environment (e.g., `myenv`):

```bash
conda list -n myenv
```

If you're already inside an activated environment, simply use:

```bash
conda list
```

---

## 🔍 Searching for Packages

To search for a package available in the conda repositories (e.g., `scipy`):

```bash
conda search scipy
```

---

## 📥 Installing Packages with Conda

To install one or more packages into an environment:

```bash
conda install --name myenv scipy curl=7.26.0
```

If you omit the `--name myenv` part, the packages will be installed in the **currently active environment**.

---

## 🌍 Using Conda-Forge and Pip

### 🧪 When to Use Conda-Forge or Pip

- Prefer `conda` for compatibility and environment management.
- Use `conda-forge` if a package is not found in the default conda channels.
- Use `pip` only if the package is unavailable through conda or conda-forge.

### 🔗 Adding Conda-Forge Channel

To add `conda-forge` and set it as the highest priority channel:

```bash
conda config --add channels conda-forge
conda config --set channel_priority strict
```

From this point, `conda install <package>` will also search conda-forge.

---

### 🐍 Installing Pip and Pip Packages

First, install `pip` if it’s not already available:

```bash
conda install pip
```

Then install the required pip package:

```bash
pip install see
```

⚠️ **Note**: Mixing conda and pip packages can lead to dependency issues. Always prefer conda when available.

---

## 📂 Updating `environment.yml` and Spec File

It’s good practice to keep your environment configuration files up to date after installing new packages. Update as follows:

### `environment.yml` (manual update required):

```bash
conda env export --name myenv > environment.yml
```

### Spec File (machine-readable):

```bash
conda list --explicit > spec-file.txt
```

Use these files to recreate environments reliably.

---


# Step 4: Managing Environment Variables in Conda

Environment variables are a critical aspect of many data science and software projects. They allow you to securely and flexibly manage sensitive credentials such as API keys, access tokens, usernames, passwords, and database configuration values—without hardcoding them into your codebase.

In this project, environment variables are especially important due to the need for managing multiple secure credentials and configuration settings. Fortunately, Conda provides built-in tools to manage these variables directly within your environment.

---

## 🔍 Viewing Environment Variables

To see which environment variables are currently defined for your active Conda environment, run:

```bash
conda env config vars list
```

---

## ➕ Setting Environment Variables

To define a new environment variable (e.g., `MY_VAR`) with a specific value:

```bash
conda env config vars set MY_VAR=value
```

You can add multiple variables at once by separating them with spaces:

```bash
conda env config vars set DB_USER=myuser DB_PASS=mypassword API_KEY=xyz123
```

---

## 🔁 Reactivating the Environment

After setting or changing environment variables, you must **reactivate your Conda environment** for the changes to take effect:

```bash
conda activate your-env-name
```

Replace `your-env-name` with the actual name of your environment (e.g., `elpis_v2`, `test-env`, etc.).

---

## ✅ Verifying Environment Variables

To confirm that an environment variable is properly set, you can either:

1. Use the `echo` command:

```bash
echo $MY_VAR        # On Linux/macOS
echo %MY_VAR%       # On Windows
```

2. Or re-run the Conda command to list environment variables:

```bash
conda env config vars list
```

---

## 🧼 Unsetting Environment Variables

If you need to remove a variable from the environment:

```bash
conda env config vars unset MY_VAR
```

Again, you’ll need to reactivate your environment after making changes:

```bash
conda activate your-env-name
```

---

#  Summary of Commands

| Task                            | Command                                                  |
|---------------------------------|-----------------------------------------------------------|
| Create project directory                      | `mkdir ~/elpis2 && cd ~/elpis2`                                      |
| Create environment with specific packages     | `conda create --no-default-packages --name elpis_v2 python=3.13.2 r-essentials r-base=4.3.1 postgresql=17.4` |
| Create environment from YAML file            | `conda env create -f environment.yml`                                |
| Export environment to YAML                   | `conda env export > environment_setup.yml`                           |
| Export explicit package list (spec file)     | `conda list --explicit > spec-file.txt`                              |
| Create environment from spec file            | `conda create --name myenv --file spec-file.txt`                     |
| Install packages from spec file              | `conda install --name myenv --file spec-file.txt`                    |
| Activate environment                         | `conda activate elpis_v2`                                            |
| Deactivate environment                       | `conda deactivate`                                                   |
| Remove environment                           | `conda remove -n ENV_NAME --all`                                     |
| List packages                   | `conda list -n myenv` or `conda list`                    |
| Search for a package            | `conda search <package>`                                 |
| Install packages                | `conda install --name myenv package1 package2=version`   |
| Add conda-forge channel         | `conda config --add channels conda-forge`                |
| Set strict channel priority     | `conda config --set channel_priority strict`             |
| Install pip                     | `conda install pip`                                      |
| Install pip package             | `pip install <package>`                                  |
| Export `environment.yml`        | `conda env export --name myenv > environment.yml`        |
| Export explicit spec file       | `conda list --explicit > spec-file.txt`                  |
| List environment variables      | `conda env config vars list`                             |
| Set environment variable        | `conda env config vars set MY_VAR=value`                 |
| Reactivate environment          | `conda activate your-env-name`                           |
| Echo variable (Unix/Windows)    | `echo $MY_VAR` / `echo %MY_VAR%`                         |
| Unset environment variable      | `conda env config vars unset MY_VAR`                     |


Keep your environments clean, reproducible, and well-documented. ✅


#  Conda Cheatsheet

This cheatsheet contains essential commands and tips for working with Conda: managing environments, installing packages, and exporting/importing configurations.

---

## 🚀 Quickstart

> 💡 **Tip:** Always create a new environment for each project or workflow.

| Task | Command |
|------|---------|
| Verify conda installation | `conda info` |
| Update conda in base env | `conda update --name base conda` |
| Install latest Anaconda | `conda install anaconda` |
| Create new environment | `conda create --name ENVNAME` |
| Activate environment | `conda activate ENVNAME` |

---

## 📚 Channels and Packages

> 💡 **Tip:** Conda resolves dependencies and platform specifics automatically.

---

## 📁 Working with Conda Environments

> 💡 **Tip:** List environments regularly. The active one is marked with an asterisk.

| Task | Command |
|------|---------|
| List all environments | `conda info --envs` |
| List packages + channels | `conda list --name ENVNAME --show-channel-urls` |
| Install packages | `conda install --name ENVNAME PKG1 PKG2` |
| Uninstall a package | `conda uninstall --name ENVNAME PKGNAME` |
| Update all packages | `conda update --all --name ENVNAME` |

---

## ⚙️ Environment Management

> 💡 **Tip:** Always specify the environment name to scope your changes.

| Task | Command |
|------|---------|
| Create env with Python version | `conda create --name ENVNAME python=3.10` |
| Clone environment | `conda create --clone ENVNAME --name NEWENV` |
| Rename environment | `conda rename --name ENVNAME NEWENVNAME` |
| Delete environment | `conda remove --name ENVNAME --all` |
| List environment revisions | `conda list --name ENVNAME --revisions` |
| Restore to a revision | `conda install --name ENVNAME --revision NUMBER` |
| Uninstall from a specific channel | `conda remove --name ENVNAME --channel CHANNELNAME PKGNAME` |

---

## 📤 Exporting Environments

> 💡 **Tip:** Use the environment name in the file name to keep things organized.

| Scope | Command |
|-------|---------|
| Cross-platform, only from history | `conda env export --from-history > ENV.yml` |
| Platform + packages | `conda env export --name ENVNAME > ENV.yml` |
| Platform + packages + channels | `conda list --explicit > ENV.txt` |

---

## 📥 Importing Environments

> 💡 **Tip:** Conda resolves platform and dependency issues during import.

| File Type | Command |
|-----------|---------|
| From `.yml` | `conda env create --name ENVNAME --file ENV.yml` |
| From `.txt` | `conda create --name ENVNAME --file ENV.txt` |

---

## 🧠 Additional Hints

| Task | Command |
|------|---------|
| Help for any command | `conda COMMAND --help` |
| Info about a package | `conda search PKGNAME --info` |
| Run without user prompts | `conda install PKG1 PKG2 --yes` |
| Clean unused files | `conda clean --all` |
| Show Conda config | `conda config --show` |

# My steps - list of what i did
