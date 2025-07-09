# Wine Manager

<div align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/Platform-Linux-lightgrey.svg" alt="Platform">
  <img src="https://img.shields.io/badge/GUI-PySide6-orange.svg" alt="GUI Framework">
</div>

A modern GUI application for managing Wine prefixes and Proton-GE installations on Linux. Features a sleek dark theme interface with comprehensive Wine prefix management, automated Proton-GE downloads, and an intuitive favorites system.
Start your .exe files the way ___you___ want!

![image](https://github.com/user-attachments/assets/20210254-80cc-480c-8f9b-5464de07f136)


## ✨ Features

### 🍷 Wine Prefix Management
- **Automatic Discovery**: Finds Wine and Bottles prefixes in standard locations (`~/.wine`, `~/.local/share/wineprefixes`, Bottles directories)
- **Custom Directories**: Add your own prefix search locations
- **Visually Appealing**: Star icons show prefixes with favorites, folder icons for regular prefixes
- **Search & Filter**: Quickly find prefixes with real-time search

### ⚙️ Proton-GE Integration
- **Automated Downloads**: Direct integration with GloriousEggroll's Proton-GE releases
- **Version Management**: Install, remove, and manage multiple Proton versions
- **Runtime Selection**: Choose between Wine or any installed Proton version

![image](https://github.com/user-attachments/assets/14f85f61-0c35-4b61-be7f-eeebcb8b4f12)


### 🎮 Application Management
- **Smart Launcher**: Browse and launch Windows applications within prefixes
- **Favorites System**: Save frequently used applications for quick access
- **System File Filtering**: Hide Windows system files to focus on user applications
- **Dual Runtime Support**: Launch apps with Wine or Proton-GE

### 🎨 User Experience
- **Dark Theme**: Modern, eye-friendly dark interface
- **Efficient Layout**: Effective use of screen space with organized sections
- **Responsive Design**: Adaptive layout that works on various screen sizes
- **Status Feedback**: Clear status messages and progress indicators
- **Comprehensive Logging**: Built-in log viewer for debugging and troubleshooting

![image](https://github.com/user-attachments/assets/93dc18b8-920d-47f2-a690-db86d46ebe00)


## 📋 Requirements

### System Requirements
- **Operating System**: Linux (tested on Ubuntu and Arch Linux)
- **Python**: 3.8 or higher
- **Wine**: Installed and configured
- **Desktop Environment**: Any (Gnome, KDE, XFCE, etc.)

### Python Dependencies
```bash
# Core dependencies
PySide6>=6.0.0      # Qt6 GUI framework
requests>=2.25.0    # HTTP requests for Proton downloads

# Standard library (included with Python)
pathlib, json, subprocess, threading, tempfile, tarfile, shutil
```

## 🚀 Installation

### Virtual Environment (Recommended)
```bash
# Create virtual environment
python3 -m venv wine-manager-env
source wine-manager-env/bin/activate

# Install dependencies
pip install PySide6 requests

# Run the application
python3 wine_manager.py
```

## 🖥️ Usage

### First Launch
1. **Start the application**: Run `python3 wine_manager.py`
2. **Automatic Scan**: The app will automatically discover existing Wine prefixes
3. **Add Custom Directories**: Use "📁 Add Dir" to include additional prefix locations
4. **Install Proton-GE**: Click "⚙️ Proton" to manage Proton versions

### Managing Wine Prefixes
- **View Prefixes**: All discovered prefixes appear in the left panel
- **Search**: Use the search box to filter prefixes by name
- **Select Runtime**: Choose Wine or Proton-GE from the runtime dropdown
- **Launch Applications**: Use "📂 choose custom .exe to run" for custom executables or "🎮 Browse Apps" to explore installed software

### Working with Favorites
- **Add Favorites**: Browse applications and add frequently used ones to favorites
- **Quick Launch**: Double-click favorites or use the "🚀 Launch" button
- **Remove Favorites**: Select and click "🗑️ Remove" to clean up your list
- **Visual Indicators**: Prefixes with favorites show a ⭐ icon and count

### Debugging and Troubleshooting
- **Access Logs**: Click "📋 Logs" to open the comprehensive log viewer
- **Filter Logs**: Use the dropdown to filter by log level (INFO, WARNING, ERROR)
- **Search Logs**: Use the search box to find specific log entries
- **Export Logs**: Save logs to a file for sharing or analysis
- **Real-time Updates**: Log viewer updates automatically as new events occur

### Proton-GE Management
- **Browse Versions**: Click "⚙️ Proton" to see available releases
- **Install Versions**: Click "⬇️ Install" next to desired versions
- **Remove Versions**: Click "🗑️ Remove" for installed versions
- **Progress Tracking**: Watch download progress in real-time

## ⚙️ Configuration

While there is no need to manually (not with the GUI) configure anything, there still is the option to do so.
This may help in error situations.
The application stores its configuration in `~/.config/wine-manager/settings.json`:

```json
{
  "proton_dir": "~/.local/share/proton-builds",
  "default_proton": "",
  "prefix_proton_map": {},
  "extra_prefix_dirs": [
    "/custom/path/to/prefixes"
  ],
  "prefix_favorites": {
    "/home/user/.wine": [
      "/home/user/.wine/drive_c/Program Files/MyApp/app.exe"
    ]
  }
}
```

### Configuration Options
- **proton_dir**: Directory where Proton-GE versions are installed
- **extra_prefix_dirs**: Additional directories to scan for prefixes
- **prefix_favorites**: Favorite applications for each prefix

## 🔧 Troubleshooting

### Common Issues

**"No prefixes found"**
- Ensure Wine is installed: `wine --version`
- Check if `~/.wine` exists or create a prefix: `winecfg`
- Add custom directories using "📁 Add Dir" button

**"Application won't launch"**
- Verify the executable path is correct
- Check Wine prefix integrity: `wine winecfg` in the prefix
- Ensure required dependencies are installed in the prefix
- **Check the logs**: Click "📋 Logs" to see detailed error messages

**"GUI looks wrong/broken"**
- Update PySide6: `pip install --upgrade PySide6`
- Try a different desktop environment
- Check if Qt6 themes are properly installed

### Debug Mode
Run with debug output:
```bash
python3 wine_manager.py 2>&1 | tee debug.log
```

### Reset Configuration
```bash
rm -rf ~/.config/wine-manager/
```

## 🤝 Contributing

I welcome contributions!


### Bug Reports
Please include:
- Operating system and version
- Python version
- Full error traceback
- Steps to reproduce the issue

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

```
MIT License

Copyright (c) 2025 ZeloteZ

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 🙏 Acknowledgments

- **[GloriousEggroll](https://github.com/GloriousEggroll)** for Proton-GE builds
- **Wine Project** for the Wine compatibility layer
- **Qt/PySide6** for the excellent GUI framework
- **Community Contributors** for testing and feedback
- **OpenAIs ChatGPT** This project relied on OpenAI’s ChatGPT for much of the code and testing.

## 📊 Project Status

- ✅ **Stable**: Core functionality is stable and tested
- 🔄 **Active Development**: Regular updates and improvements
  

## 🔗 Related Projects

- [Wine](https://www.winehq.org/) - Windows compatibility layer
- [Proton-GE](https://github.com/GloriousEggroll/proton-ge-custom) - Enhanced Proton builds
- [Bottles](https://usebottles.com/) - Another Wine prefix manager

---

<div align="center">
  <p>Made with ❤️ for the Linux gaming community</p>
  <p>
    <a href="#wine-manager">Back to Top</a> •
    <a href="https://github.com/ZeloteZ/wine-manager/issues">Report Bug</a> •
    <a href="https://github.com/ZeloteZ/wine-manager/issues">Request Feature</a>
  </p>
</div>
