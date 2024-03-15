
## Overview
`strawberry-autograph` is a testing library designed to extend Strawberry's test client capabilities by automatically generating operation strings for queries and mutations. This allows for streamlined testing of GraphQL schemas, focusing on testing schema logic directly with Strawberry input objects.

## Installation
Add `strawberry-autograph` to your project using Poetry or pip:
```bash
poetry add strawberry-autograph
```
or
```bash
pip install strawberry-autograph
```
Ensure you have Strawberry GraphQL installed as it's an optional dependency:
```bash
poetry add strawberry-graphql
```

## Features
- **Operation Autogeneration**: Dynamically creates operation strings for testing.
- **Seamless Integration**: Wraps around Strawberry's test client, enhancing its functionality.

## Usage
`strawberry-autograph` simplifies writing tests for Strawberry schemas by using defined inputs directly in test cases.

### Testing Mutations with Inputs
Define your schema with a mutation that takes a Strawberry input:

```python
import strawberry

@strawberry.input
class CookEggInput:
    minutes: int

@strawberry.type
class Mutation:
    @strawberry.mutation
    def cook_egg(self, egg_op: CookEggInput) -> str:
        return "cooked" if input.minutes > 3 else "raw"

schema = strawberry.Schema(mutation=Mutation)
```
Use strawberry-autograph to automatically generate the mutation operation string and execute it with the Strawberry test client:

```python
from strawberry_autograph import AutoGraphClient
from myapp.schema import schema  # Your Strawberry graphql schema object

def test_cook_egg():
    client = AutoGraphClient(schema)
    result = client.cook_egg(
        egg_op=CookEggInput(minutes=4)
    )
    assert result.data == {"cookEgg": "cooked"}
```
This library enables focused and efficient testing of GraphQL logic, directly utilizing Strawberry types and inputs.

## Development Status
`strawberry-autograph` is currently in alpha (v0.1.0) and open to contributions. As an evolving project, feedback and improvements are welcome to refine its functionality and user experience.
