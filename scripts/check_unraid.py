"""Validate the installation contract without requiring an Unraid host."""
from pathlib import Path
import xml.etree.ElementTree as ET

root = ET.parse(Path(__file__).resolve().parents[1] / 'unraid/family-os.xml').getroot()
assert root.tag == 'Container' and root.attrib['version'] == '2'
assert root.findtext('Repository') == 'ghcr.io/tobim-dev/family-os:latest'
assert root.findtext('Privileged') == 'false'
configs = {entry.attrib['Target']: entry for entry in root.findall('Config')}
assert len(configs) == len(root.findall('Config')), 'Duplicate configuration target'
assert configs['/data'].attrib['Type'] == 'Path'
assert configs['FOS_DEMO'].text == '0'
assert configs['FOS_ORIGIN'].text.startswith('https://')
assert configs['FOS_DB'].text == '/data/family.sqlite'
assert configs['8000'].attrib['Type'] == 'Port'
assert configs['FOS_ANTHROPIC_API_KEY'].attrib['Mask'] == 'true' and not (configs['FOS_ANTHROPIC_API_KEY'].text or '').strip(), 'API key must be masked and empty'
assert '--cap-drop=ALL' in root.findtext('ExtraParams')
assert '--privileged' not in root.findtext('ExtraParams')
print('Unraid template: installation contract valid.')
