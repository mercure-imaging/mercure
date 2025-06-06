# -*- coding: utf-8 -*-
#
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.abspath('../app'))


# -- Project information -----------------------------------------------------

project = 'mercure'
copyright = '2019-2025 The "mercure" authors and contributors'
author = ''
def read_version() -> str:
    current_version = "0.0.0"
    version_filepath = os.path.dirname(os.path.realpath(__file__)) + '/../app/VERSION'
    version_file = Path(version_filepath)
    with open(version_file, "r") as version_filecontent:
        current_version = version_filecontent.readline().strip()
    return "Version " + current_version

# The short X.Y version
#version = 'Version 0.2'
version = read_version()

# The full version, including alpha/beta/rc tags
release = version


# -- General configuration ---------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
#
# needs_sphinx = '1.0'

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.todo',
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.githubpages'
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# The suffix(es) of source filenames.
# You can specify multiple suffix as a list of string:
#
# source_suffix = ['.rst', '.md']
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = 'en'

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path .
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
#
html_theme_options = {
    'logo_only': True,
    'style_external_links': True,
    'display_version': True,
    'sticky_navigation': False,
    'navigation_depth': 2
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']
html_css_files = ['custom.css']

# Custom sidebar templates, must be a dictionary that maps document names
# to template names.
#
# The default sidebars (for documents that don't match any pattern) are
# defined by theme itself.  Builtin themes are using these templates by
# default: ``['localtoc.html', 'relations.html', 'sourcelink.html',
# 'searchbox.html']``.
#
# html_sidebars = {}
html_theme = 'sphinx_rtd_theme'
html_logo = 'images/mercure_logo_w.png'
html_show_sourcelink = False


autodoc_default_options = {
    'members': True,
    'undoc-members': True,
    'show-inheritance': True,    
}
