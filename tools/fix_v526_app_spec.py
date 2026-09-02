from pathlib import Path
import subprocess

subprocess.run(['git', 'checkout', 'origin/main', '--', 'source/app.spec'], check=True)
p = Path('source/app.spec')
data = p.read_bytes()
data = data.replace(b'5.2.5', b'5.2.6').replace(b'50205', b'50206')
p.write_bytes(data)
