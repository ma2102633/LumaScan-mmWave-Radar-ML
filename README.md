# LumaScan-mmWave-Radar-ML
Source code for LumaScan: an early, non-invasive breast cancer detection research prototype using mmWave radar, X-Y scanning, signal processing, and machine learning.

# LumaScan: mmWave Radar and Machine Learning Breast Cancer Detection Prototype

This repository contains the source code developed for the senior project:

**An Early, Non-Invasive Breast Cancer Detection System Using mmWave Radar and Machine Learning**

## Project Overview

LumaScan is a research prototype that combines mmWave radar, an automated X-Y scanning platform, radar signal processing, heatmap generation, and machine learning classification to support early breast cancer detection research.

The system uses radar data collected from controlled phantom experiments. The scanner moves in an X-Y pattern, stops at each grid point, captures radar data, and then processes the collected signals into visual heatmaps for analysis.

## Repository Structure

- `radar_scanning/`  
  Contains ESP32 motion-control code and Python scripts used for radar data acquisition.

- `signal_processing/`  
  Contains Python scripts for reading raw radar files, extracting coordinates, applying FFT-based processing, generating heatmaps, and comparing tumour/no-tumour/background scans.

- `machine_learning/`  
  Contains the machine learning and deep learning model code used for classification experiments.

- `sample_outputs/`  
  Contains selected non-sensitive output figures used for report demonstration.

## Notes

Raw radar dataset files are not included in this repository because they are large and used only for controlled project experiments.

## Team Members

- Nagham Alajmi
- Noor Alkaabi
- Maryam Alkaabi
- Lama AlDosari

## Supervisor

Dr. Sumaya Al-Maadeed

## University

Qatar University  
College of Engineering  
Department of Computer Science and Engineering
