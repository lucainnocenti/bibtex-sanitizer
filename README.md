# bibtexsanitizer
Simple python package to manage and sanitize .bib files.

# Installation

From the terminal, `cd` to your directory of choice (`/usr/local/share` can be a good choice, depending on your distribution),
and execute the following commands:
```bash
git clone https://github.com/lucainnocenti/bibtex-sanitizer
cd bibtex-sanitizer
pip install -e .
```
This will install the package into the current python environment.
To later use the package in a script, import it with `import bibtexsanitizer`.

The script `pybib.py` allows to use `bibtexsanitizer` via command line, without the need to explicitly evoke `python`.
To more easily use this script, you might want to alias it. For example, if you cloned the repository in `/usr/local/share`,
add the following line to your `~/.bashrc` (or `~/.zshrc`, or equivalent for your shell):
```bash
alias pybib=/usr/local/share/bibtex-sanitizer/pybib.py
```
Run the following to test that everything is working as intended: `pybib print arxiv 1801.1234`.

# Usage examples

Print and copy to clipboard the entry corresponding to the DOI in a given url:

```bash
pybib print doi https://journals.aps.org/prl/abstract/10.1103/PhysRevLett.102.193601
```

Print and copy to clipboard entries corresponding to multiple given DOIs

```bash
pybib print doi 10.1103/PhysRevLett.122.020503 10.1103/PhysRevA.96.062326 10.1088/1367-2630/aaad92
```
