# -*- coding: utf-8 -*-
"""
Created on Thu Jun 11 22:12:24 2026

@author: michi
"""
import pandas as pd


DATA_PATH = "golf_shots.csv"

data = pd.read_csv(DATA_PATH)



for idx, row in data.iterrows():
    
    shot_str = f"{row['round_date']} | hole {row['hole']} | shot {row['shot']} | "
    
    # Teeshots
    if row["shot"] == 1:
        assert row["lie"] == "rough", shot_str + "Tee shot from non-teebox lie"
        
    # Putter    
    if row["club"] == "Putter":
        assert row["distance_m"] < 30, shot_str + "putter distance > 30m"
        assert row["lie"] == "green", shot_str + "putting from off the green"
        
        