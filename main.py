# -*- coding: utf-8 -*-
"""
Created on Wed Oct 22 21:03:59 2025

@author: michi
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns


class Analytics():
    def __init__(self, dataframe: pd.DataFrame):
        self.df = self.clean_data(dataframe)
        self.COLORS = ['red', 'blue', 'green', 'orange', 'purple']
        self.club_types = self.df["Club Type"].unique()

    def clean_data(self, dataframe):
        
        # Convert columns to numeric
        for col in dataframe.columns:
            try:
                dataframe[col] = pd.to_numeric(dataframe[col])
            except Exception:
                dataframe[col] = dataframe[col].astype(object)
                
        return dataframe

    def plots(self):
        def scatter(xarg, yarg):
            
            fig, ax = plt.subplots()
            for i, club in enumerate(self.club_types):
                df_club = self.df.loc[df["Club Type"]==club]
                ax.scatter(
                    x=df_club[xarg], 
                    y=df_club[yarg],
                    color=self.COLORS[i % len(self.COLORS)],
                    label=club
                    )
            plt.xlabel(xarg)
            plt.ylabel(yarg)
            plt.title(f"{yarg} & {xarg} by Club Type")
            plt.legend(
                title="Club Type",
                bbox_to_anchor=(1.05, 1), 
                loc='upper left',
                framealpha=0.9,
                edgecolor='black'
            )
            
        def boxplot(arg):
            fig, ax = plt.subplots()
            data = []
            labels = []
            for club in self.club_types:
                df_club = self.df[self.df["Club Type"] == club]
                data.append(df_club[arg].dropna())  # drop NaN values
                labels.append(club)
            
            # Create boxplot
            ax.boxplot(
                data, 
                tick_labels=labels,
                orientation="horizontal"
                )
                
        def histogram(arg):
            sns.set_style("whitegrid")  # Clean background with grid
            palette = sns.color_palette("Set2", len(self.club_types))
            
            fig, ax = plt.subplots()
            for i, club in enumerate(self.club_types):
                df_club = self.df.loc[self.df["Club Type"] == club]
                
                sns.histplot(df_club[arg], bins=20, kde=True, color=palette[i], label=club, alpha=0.6)
               
                plt.xlabel(arg, fontsize=14)
                plt.ylabel("Frequency", fontsize=14)
                plt.title(f"Histogram of {arg} by Club Type", fontsize=16, weight='bold')
                plt.legend(
                    title="Club Type",
                    bbox_to_anchor=(1.05, 1), 
                    loc='upper left',
                    framealpha=0.9
                )
                
                plt.show()
                
            return
                
        graph_dict = {
            "scatter": scatter,
            "boxplot": boxplot,
            "histogram": histogram
            }

        return graph_dict
    
    
    
if __name__ == "__main__":
    
    plt.style.use('_mpl-gallery')
    
    df = pd.read_csv("data.csv").loc[1:]
    
    app = Analytics(df)
    app.plots()["histogram"](arg="Total Distance")
    plt.show()
    