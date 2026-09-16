pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'webarchive'
gnome = import('gnome')
gnome.compile_resources('webarchive',
  'webarchive.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,)
python = import('python')
conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('VERSION', meson.project_version())
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('pkgdatadir', pkgdatadir)
configure_file(
  input: 'webarchive.in',
  output: 'webarchive',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x')
webarchive_sources = files(
  'main.py',
  'webarchive/app.py',
  'webarchive/home.py',
  'webarchive/__init__.py',
  'webarchive/kiwix_lib.py',
  'webarchive/state.py',
  'webarchive/window.py',
  'webarchive/zim.py',
  'webarchive/welcome.py',
  'webarchive/downloads.py',
  'webarchive/downloads_ui.py',
)
install_data(webarchive_sources, install_dir: moduledir)