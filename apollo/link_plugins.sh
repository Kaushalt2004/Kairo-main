mkdir -p /apollo/share/cyber_plugin_index
for f in $(find /apollo/modules -name cyberfile.xml | grep plugin); do
  name=$(basename $(dirname $f))
  ln -sf $f /apollo/share/cyber_plugin_index/${name}.xml
done
