# Synergi Lead Filter

Offline Windows GUI to filter Companies House bulk CSVs into priority, potential, and review leads based on SIC codes and company names. Original CSV is never modified. Streaming CSV processing keeps memory use low.

## Download EXE
Open **Actions → Build portable Windows EXE → latest successful run → Artifacts → SynergiLeadFilter-Windows**. Unzip and double-click the EXE. No Python installation is needed on the target Windows computer.

## Usage
Select the Companies House CSV and an output folder, then click **Filter companies**. Three CSV files will be created. Inspect the review file before discarding leads; SIC filtering is a rough first pass and does not validate company websites or project suitability.

The build runs on GitHub; the input CSV is processed locally and is never uploaded.

## Security
Review source and GitHub workflow before running a downloaded executable. Windows SmartScreen may flag an unsigned EXE.
