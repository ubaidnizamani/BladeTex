# BladeTex

**BladeTex** is a modern, standalone desktop application built for managing, unpacking, packing, and converting texture archives (`.mmp`) and asset files for the game ***Severance: Blade of Darkness***.

---

## How to Use

Because **BladeTex** is packaged as a standalone application, you do **not** need Python or any external libraries installed on your computer.

1. Simply double-click **`BladeTex.exe`** to launch the application.
2. **Drag and drop** your `.mmp` archive files, folders, or texture images directly into the application window's drop zone or file explorer.
3. Select your preferred options (Target BPP, image formats, or custom output directories) and click the respective action buttons.

---

## Features

* **Interactive File Explorer & Tree View:** Drag and drop files or folders with real-time structural inspection and item selection.
* **Live Texture Preview:** Preview texture slices instantly inside the application before extracting or modifying them.
* **MMP Archive Management:**
  * **Unpacking:** Extract all or selective texture slices from `.mmp` files into standard image formats.
  * **Packing:** Pack image folders back into fully compliant `.mmp` archives with configurable bitrates (`32`, `24`, `8`, or `Alpha`).
  * **Bitrate Conversion (`tobpp`):** Quickly re-encode MMP color depths.
  * **DAT Generation:** Bundle or convert archives into `.dat` format.
* **Image Transcoding:** Convert textures across modern formats (**PNG**, **JPG**, **BMP**, **WEBP**) with multi-core parallel processing.
* **Advanced Utilities:**
  * Standard folder unification (`StdUnify`).
  * RGB/BGR color channel channel swapping to fix color inversion issues.
  * Batch texture removal and purging inside archives.

---

## Acknowledgments & Credits

BladeTex's workflow automation and graphical interface wrap around core texture conversion routines and parsing logic heavily inspired by and adapted from **Sryml**'s original `mmp_convert.py` for *Severance: Blade of Darkness*.

* Special thanks to **Sryml** for laying down the foundational Python script code, parsing logic, and format handling specifications for MMP archives, making texture modding for the game possible.