# Contributing to Grocery Agent

First off, thank you for considering contributing to Grocery Agent! It's people like you that make this educational project such a great resource for learning production-grade Python development.

## Code of Conduct

This project and everyone participating in it is governed by our Code of Conduct. By participating, you are expected to uphold this code.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check the issue list as you might find out that you don't need to create one. When you are creating a bug report, please include as many details as possible:

- **Use a clear, descriptive title**
- **Describe the exact steps which reproduce the problem**
- **Provide specific examples to demonstrate the steps**
- **Describe the behavior you observed after following the steps**
- **Explain which behavior you expected to see instead and why**
- **Include screenshots and animated GIFs if possible**
- **Include your environment details:**
  - Python version
  - OS and version
  - Model being used
  - Any customizations to configuration

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion, please include:

- **Use a clear, descriptive title**
- **Provide a step-by-step description of the suggested enhancement**
- **Provide specific examples to demonstrate the steps**
- **Describe the current behavior and expected behavior**
- **Explain why this enhancement would be useful**

### Pull Requests

- Fill in the required template
- Follow the Python styleguides
- Include appropriate test cases
- End all files with a newline
- Avoid platform-dependent code

## Styleguides

### Git Commit Messages

- Use the present tense ("Add feature" not "Added feature")
- Use the imperative mood ("Move cursor to..." not "Moves cursor to...")
- Limit the first line to 72 characters or less
- Reference issues and pull requests liberally after the first line
- Example:
  ```
  Add config management system
  
  - Implement Config class with environment variable support
  - Add .env file support with python-dotenv
  - Include DevelopmentConfig, ProductionConfig, TestingConfig
  
  Closes #42
  ```

### Python Styleguide

Follow PEP 8 with these additional requirements:

#### Type Hints
All functions must have type hints:

```python
# ✅ Good
def add_item(item: str) -> None:
    """Add item to pantry."""
    pass

# ❌ Bad
def add_item(item):
    """Add item to pantry."""
    pass
```

#### Docstrings
Use Google-style docstrings:

```python
def generate_shopping_list(meal_plan: List[Dict]) -> List[str]:
    """Generate shopping list from meal plan.
    
    Filters out items already in pantry and removes duplicates
    while preserving insertion order.
    
    Args:
        meal_plan: List of meals with ingredients.
    
    Returns:
        List of shopping list items, deduplicated.
    
    Raises:
        TypeError: If meal_plan is not a list.
        ValueError: If meal_plan contains invalid items.
    """
    pass
```

#### Error Handling
Always handle errors gracefully:

```python
# ✅ Good
try:
    data = json.load(f)
except json.JSONDecodeError as e:
    logger.error(f"Failed to parse file: {e}")
    return []

# ❌ Bad
try:
    data = json.load(f)
except:
    pass  # Silent failure
```

#### Logging
Use structured logging:

```python
# ✅ Good
logger.info(f"Generated shopping list with {len(items)} items")
logger.error(f"Failed to save pantry: {e}")

# ❌ Bad
print("Done")
print("Error!")
```

#### Code Example

```python
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

def process_items(items: List[str], filter_str: Optional[str] = None) -> List[str]:
    """Process and optionally filter items.
    
    Args:
        items: List of items to process.
        filter_str: Optional filter string (case-insensitive).
    
    Returns:
        Processed list of items.
    
    Raises:
        TypeError: If items is not a list.
    """
    if not isinstance(items, list):
        raise TypeError(f"Expected list, got {type(items).__name__}")
    
    try:
        result = []
        for item in items:
            if isinstance(item, str):
                processed = item.strip().lower()
                if filter_str is None or filter_str.lower() in processed:
                    result.append(processed)
        
        logger.info(f"Processed {len(result)} items")
        return result
    
    except Exception as e:
        logger.error(f"Error processing items: {e}")
        raise
```

## Development Setup

### 1. Fork and Clone
```bash
git clone https://github.com/ShiyanYang/receipt_agent.git
cd receipt_agent
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Development Dependencies
```bash
pip install -r requirements.txt
# Optional: pip install pytest pytest-cov black pylint mypy
```

### 4. Create Feature Branch
```bash
git checkout -b feature/your-feature-name
```

### 5. Make Your Changes
- Write code following styleguides
- Add/update tests
- Update documentation

### 6. Test Your Changes
```bash
# Test import
python -c "from agent import Agent; print('✅ Import successful')"

# Run the app
python main.py

# Run pantry manager
python app.py

# Run evaluation (if applicable)
python eval.py
```

### 7. Commit and Push
```bash
git add .
git commit -m "Add your feature"
git push origin feature/your-feature-name
```

### 8. Create Pull Request
- Go to GitHub and create a pull request
- Fill in the PR template
- Link any related issues
- Wait for review

## Testing Guidelines

### Writing Tests
If adding new features, include tests:

```python
# tests/test_pantry.py
import pytest
from pantry import add_item, remove_item, list_items

def test_add_item():
    """Test adding an item to pantry."""
    items_before = len(list_items())
    add_item("test_item")
    items_after = len(list_items())
    assert items_after == items_before + 1

def test_add_duplicate_item():
    """Test that duplicate items aren't added."""
    add_item("duplicate_test")
    count_before = len(list_items())
    add_item("duplicate_test")
    count_after = len(list_items())
    assert count_before == count_after
```

### Running Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_pantry.py
```

## Documentation

### Updating README
- If adding a new feature, update the README.md
- Add examples of how to use the feature
- Update the architecture section if needed

### Adding Docstrings
- All modules should have module-level docstrings
- All classes should have class-level docstrings
- All public functions should have function docstrings

### Creating New Documentation
For major features, consider adding:
- Example usage in README
- Separate documentation file
- Code comments for complex logic

## Questions?

- Check existing issues and discussions
- Create a new discussion for questions
- Review [PRODUCTION_IMPROVEMENTS.md](PRODUCTION_IMPROVEMENTS.md) for context

## Additional Notes

### Project Goals
This is an **educational project** designed to demonstrate:
- Production-grade Python development
- AI model integration
- Software architecture patterns
- Best practices for file I/O, configuration, logging

### Learning Focus Areas
- Type safety and validation
- Error handling and recovery
- Data persistence and atomicity
- Configuration management
- Code organization and documentation

### Future Directions
See [PRODUCTION_IMPROVEMENTS.md](PRODUCTION_IMPROVEMENTS.md) for planned improvements and next steps.

---

Thank you for contributing! 🎉
