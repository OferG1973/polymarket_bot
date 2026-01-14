import pandas as pd

df = pd.read_csv("data_BTC.csv")
print(f"Total Rows: {len(df)}")
print("Outcome Counts:")
print(df['outcome'].value_counts())