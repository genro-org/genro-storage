# genro-storage Interactive Tutorials

Welcome! These Jupyter notebooks provide hands-on, interactive tutorials for
learning genro-storage. They are executed by the test suite
(`tests/test_notebooks.py`) on every run, so what they show is what the current
release does.

## 🚀 Quick Start

### Option 1: Run Locally

```bash
# Install genro-storage and Jupyter
pip install genro-storage jupyter notebook

# Launch from this directory
jupyter notebook

# Open 01_quickstart.ipynb and start learning!
```

### Option 2: Run From a Clone, Without Installing

The package lives in `src/`, so pointing `PYTHONPATH` at it is enough. Its
runtime dependencies still have to be there — only genro-storage itself is not
installed:

```bash
pip install jupyter notebook fsspec PyYAML genro-toolbox genro-builders genro-bag
PYTHONPATH=../src jupyter notebook
```

**Important:** Execute notebook cells **sequentially from top to bottom** using `Shift+Enter`. Variables persist between cells!

## 📚 Learning Path

The notebooks are designed to be followed in order, from beginner to advanced:

| Notebook | Topic | Duration | Level |
|----------|-------|----------|-------|
| [01_quickstart.ipynb](01_quickstart.ipynb) | Quick start and basic concepts | 15 min | Beginner |
| [02_backends_and_mounts.ipynb](02_backends_and_mounts.ipynb) | Storage backends and configuration | 20 min | Beginner |
| [03_file_operations.ipynb](03_file_operations.ipynb) | File and directory operations | 25 min | Beginner |
| [04_virtual_nodes.ipynb](04_virtual_nodes.ipynb) | Virtual nodes: iternode, diffnode, zip | 30 min | Intermediate |
| [05_copy_strategies.ipynb](05_copy_strategies.ipynb) | Copy strategies and filtering | 25 min | Intermediate |
| [06_versioning.ipynb](06_versioning.ipynb) | S3 versioning features | 30 min | Intermediate |
| [07_advanced_features.ipynb](07_advanced_features.ipynb) | Advanced features and integrations | 35 min | Advanced |
| [08_real_world_examples.ipynb](08_real_world_examples.ipynb) | Complete real-world use cases | 40 min | Advanced |

**Total time:** ~3.5 hours (but you can skip around!)

### Optional: Cloud Storage Examples

Most examples use in-memory storage, but if you want to try S3/GCS/Azure examples:

```bash
pip install genro-storage[s3]    # Amazon S3
pip install genro-storage[gcs]   # Google Cloud Storage
pip install genro-storage[azure] # Azure Blob Storage
```

## 📖 What You'll Learn

### For Beginners

**Notebooks 1-3** cover the fundamentals:
- Setting up storage backends (local, memory, S3, etc.)
- Reading and writing files
- Working with directories
- Copying and moving files
- Path navigation and properties

### For Intermediate Users

**Notebooks 4-6** explore powerful features:
- Virtual nodes for lazy operations
- Smart copy strategies to save bandwidth
- File filtering and pattern matching
- S3 versioning and rollback
- Version comparison and compaction

### For Advanced Users

**Notebooks 7-8** dive into advanced scenarios:
- External tool integration (ffmpeg, imagemagick)
- Web framework integration (Flask, Django)
- Cloud metadata and presigned URLs
- Complete real-world applications

## 🎯 Learning Approach

Each notebook includes:

- **Clear explanations** of concepts
- **Runnable code examples** you can execute
- **Try it yourself** sections for experimentation
- **Real-world scenarios** and best practices
- **Exercises** to reinforce learning (optional)
- **Links** to relevant documentation

## 💡 Tips

- **Run cells sequentially** - notebooks build on previous cells
- **Experiment freely** - all examples use safe in-memory storage by default
- **Read the comments** - code is heavily documented
- **Try variations** - modify examples to explore behavior
- **Skip what you know** - each notebook is relatively self-contained

## 🔍 Quick Reference

Need to find something specific?

- **Basic file I/O**: Notebook 3
- **Concatenating files**: Notebook 4 (iternode)
- **Comparing files**: Notebook 4 (diffnode)
- **Creating archives**: Notebook 4 (zip)
- **Incremental backups**: Notebook 5 (skip strategies)
- **File versioning**: Notebook 6
- **External commands**: Notebook 7 (call method)
- **Web serving**: Notebook 7 (serve method)

## 🐛 Troubleshooting

- **Import errors**: Make sure genro-storage is installed: `pip install genro-storage`
- **S3 errors**: Install S3 support: `pip install genro-storage[s3]`
- **Permission errors**: Check your AWS credentials if using S3 examples
- **Kernel issues**: Restart kernel and run all cells from the beginning

## 📝 Contributing

Found a typo? Have a better example? Contributions welcome!

1. Edit the notebook
2. Clear all outputs: `Cell -> All Output -> Clear`
3. Submit a pull request

## 📚 Additional Resources

- [Documentation](https://genro-storage.readthedocs.io/)
- [API Reference](../docs/api_reference.rst)
- [GitHub Repository](https://github.com/genropy/genro-storage)
- [Issue Tracker](https://github.com/genropy/genro-storage/issues)

## 🎓 Ready to Start?

Begin with [01_quickstart.ipynb](01_quickstart.ipynb) for a gentle introduction!

Happy learning! 🚀
