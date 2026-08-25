# GenderScope Python

```sh
pip install genderscope
```

```python
from genderscope import GenderScope
client = GenderScope("YOUR_API_KEY")
result = client.name("Ayşe", country="TR")
print(result["gender"], result["confidence"])
```
