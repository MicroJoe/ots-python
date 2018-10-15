from __future__ import print_function, absolute_import
from setuptools import setup, find_packages, Extension, Command
from setuptools.command.build_ext import build_ext
from distutils.file_util import copy_file
from distutils.dir_util import mkpath, remove_tree
from distutils import log
import os
import sys
import subprocess

if sys.version_info[:2] < (3, 6):
    sys.exit(
        "error: Python 3.6 is required to run setup.py. \n"
        "The generated wheel will be compatible with both py27 and py3+"
    )

cmdclass = {}
try:
    from wheel.bdist_wheel import bdist_wheel
except ImportError:
    pass
else:

    class UniversalBdistWheel(bdist_wheel):
        def get_tag(self):
            return ("py2.py3", "none") + bdist_wheel.get_tag(self)[2:]

    cmdclass["bdist_wheel"] = UniversalBdistWheel


class Download(Command):

    user_options = [
        ("version=", None, "ots source version number to download"),
        ("sha256=", None, "expected SHA-256 hash of the source archive"),
        ("download-dir=", "d", "where to unpack the 'ots' dir (default: src/c)"),
        ("clean", None, "remove existing directory before downloading"),
    ]
    boolean_options = ["clean"]

    URL_TEMPLATE = (
        "https://github.com/khaledhosny/ots/releases/download/"
        "v{version}/ots-{version}.tar.xz"
    )

    def initialize_options(self):
        self.version = None
        self.download_dir = None
        self.clean = False
        self.sha256 = None

    def finalize_options(self):
        if self.version is None:
            from distutils.errors import DistutilsSetupError

            raise DistutilsSetupError("must specify --version to download")

        if self.sha256 is None:
            from distutils.errors import DistutilsSetupError

            raise DistutilsSetupError("must specify --sha256 of downloaded file")

        if self.download_dir is None:
            self.download_dir = os.path.join("src", "c")

        self.url = self.URL_TEMPLATE.format(**vars(self))

    def run(self):
        from urllib.request import urlopen
        from io import BytesIO
        import tarfile
        import lzma
        import hashlib

        output_dir = os.path.join(self.download_dir, "ots")
        if self.clean and os.path.isdir(output_dir):
            remove_tree(output_dir, verbose=self.verbose, dry_run=self.dry_run)

        if os.path.isdir(output_dir):
            log.info("{} was already downloaded".format(output_dir))
        else:
            archive_name = self.url.rsplit("/", 1)[-1]

            mkpath(self.download_dir, verbose=self.verbose, dry_run=self.dry_run)

            log.info("downloading {}".format(self.url))
            if not self.dry_run:
                # response is not seekable so we first download *.tar.xz to an
                # in-memory file, and then extract all files to the output_dir
                # TODO: use hashlib to verify the SHA-256 hash
                f = BytesIO()
                with urlopen(self.url) as response:
                    f.write(response.read())
                f.seek(0)

            actual_sha256 = hashlib.sha256(f.getvalue()).hexdigest()
            if actual_sha256 != self.sha256:
                from distutils.errors import DistutilsSetupError

                raise DistutilsSetupError(
                    "invalid SHA-256 checksum:\n"
                    "actual:   {}\n"
                    "expected: {}".format(actual_sha256, self.sha256)
                )

            log.info("unarchiving {} to {}".format(archive_name, output_dir))
            if not self.dry_run:
                with lzma.open(f) as xz:
                    with tarfile.open(fileobj=xz) as tar:
                        filelist = tar.getmembers()
                        first = filelist[0]
                        if not (first.isdir() and first.name.startswith("ots")):
                            from distutils.errors import DistutilsSetupError

                            raise DistutilsSetupError(
                                "The downloaded archive is not recognized as "
                                "a valid ots source tarball"
                            )
                        # strip the root 'ots-X.X.X' directory before extracting
                        rootdir = first.name + "/"
                        to_extract = []
                        for member in filelist[1:]:
                            if member.name.startswith(rootdir):
                                member.name = member.name[len(rootdir) :]
                                to_extract.append(member)
                        tar.extractall(output_dir, members=to_extract)


class Executable(Extension):

    if os.name == "nt":
        suffix = ".exe"
    else:
        suffix = ""

    def __init__(self, name, script, output_dir=".", cwd=None, env=None):
        Extension.__init__(self, name, sources=[])
        self.target = self.name.split(".")[-1]
        self.script = script
        self.output_dir = output_dir
        self.cwd = cwd
        self.env = env


class ExecutableBuildExt(build_ext):
    def get_ext_filename(self, ext_name):
        for ext in self.extensions:
            if isinstance(ext, Executable):
                return os.path.join(*ext_name.split(".")) + ext.suffix
        return build_ext.get_ext_filename(self, ext_name)

    def run(self):
        self.run_command("download")
        build_ext.run(self)

    def build_extension(self, ext):
        if not isinstance(ext, Executable):
            build_ext.build_extension(self, ext)
            return

        cmd = [sys.executable, ext.script, ext.target]
        if self.force:
            cmd += ["--force"]
        log.debug("running '{}'".format(" ".join(cmd)))
        if not self.dry_run:
            p = subprocess.run(cmd, cwd=ext.cwd, env=ext.env)
            if p.returncode != 0:
                from distutils.errors import DistutilsExecError

                raise DistutilsExecError(
                    "running '{}' script failed".format(ext.script)
                )

        exe_name = ext.target + ext.suffix
        exe_fullpath = os.path.join(ext.output_dir, exe_name)

        dest_path = self.get_ext_fullpath(ext.name)
        mkpath(os.path.dirname(dest_path), verbose=self.verbose, dry_run=self.dry_run)

        copy_file(exe_fullpath, dest_path, verbose=self.verbose, dry_run=self.dry_run)


cmdclass = {"download": Download, "build_ext": ExecutableBuildExt}

ots_sanitize = Executable(
    "ots.ots-sanitize", script="build.py", output_dir=os.path.join("build", "meson")
)

with open("README.md", "r", encoding="utf-8") as readme:
    long_description = readme.read()

setup(
    name="opentype-sanitizer",
    use_scm_version={"write_to": "src/python/ots/_version.py"},
    description=("Python wrapper for the OpenType Sanitizer"),
    long_description=long_description,
    author="Cosimo Lupo",
    author_email="cosimo@anthrotype.com",
    url="https://github.com/anthrotype/ots-python",
    license="MIT",
    platforms=["posix", "nt"],
    package_dir={"": "src/python"},
    packages=find_packages("src/python"),
    ext_modules=[ots_sanitize],
    zip_safe=False,
    cmdclass=cmdclass,
    setup_requires=["setuptools_scm"],
    extras_require={"testing": ["pytest"]},
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Environment :: Other Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 3",
        "Topic :: Text Processing :: Fonts",
        "Topic :: Multimedia :: Graphics",
    ],
)
