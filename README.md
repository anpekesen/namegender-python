# NameGender Python

```sh
pip install namegender-client
```

```python
from namegender import NameGender
client = NameGender("YOUR_API_KEY")
result = client.name("Ayşe", country="TR")
print(result["gender"], result["confidence"])
```
