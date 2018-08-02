from setuptools import setup

setup(
	name="bibtexsanitizer",
	version="0.1",
	py_modules=["bibtexsanitizer"],

	# dependencies
	install_requires=[
		'bibtexparser',
		'arxiv',
	],

	# metadata for upload to PyPI
	author="Luca Innocenti",
	author_email="lukeinnocenti@gmail.com",
	description="Python module to manage .bib files.",
	license="MIT",
	keywords="arxiv api wrapper academic journals papers bib biblatex",
	url="https://github.com/lucainnocenti/bibtex-sanitizer"
)
