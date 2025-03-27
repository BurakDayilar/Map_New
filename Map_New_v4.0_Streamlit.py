import streamlit as st
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import folium
from streamlit_folium import st_folium
import matplotlib.patches as mpatches
import io
import tempfile
import os
import zipfile
from pathlib import Path
from branca.element import Element
from fpdf import FPDF

st.set_page_config(page_title="Color Map Automation", layout="wide")
st.title("🗺️ Color Map Automation")

MAP_DB_DIR = "maps"
os.makedirs(MAP_DB_DIR, exist_ok=True)

st.sidebar.header("1. Select or Add Map")
map_files = [f for f in os.listdir(MAP_DB_DIR) if f.endswith(".geojson") or f.endswith(".json")]
selected_map_file = st.sidebar.selectbox("Choose a map", ["-- Upload New Map --"] + map_files)

if selected_map_file == "-- Upload New Map --":
    uploaded_map = st.sidebar.file_uploader("Upload New GeoJSON Map", type=["geojson", "json"])
    if uploaded_map:
        new_map_path = os.path.join(MAP_DB_DIR, uploaded_map.name)
        with open(new_map_path, "wb") as f:
            f.write(uploaded_map.read())
        st.sidebar.success(f"Map '{uploaded_map.name}' added to database. Please select it from the list.")
        st.stop()
else:
    geojson_path = os.path.join(MAP_DB_DIR, selected_map_file)
    geo_data = gpd.read_file(geojson_path)
    geo_data = geo_data.to_crs(epsg=4326)

    st.success(f"Map loaded: {selected_map_file}")
    st.subheader("💾 Region Names in Map")
    if "name" in geo_data.columns:
        region_names = geo_data["name"].dropna().unique()
        st.write(pd.DataFrame(region_names, columns=["Region Name"]))
        txt_data = "\n".join(region_names)
        st.download_button("📄 Download Region Names (.txt)", txt_data, file_name="region_names.txt")
        region_df = pd.DataFrame(region_names, columns=["Region Name"])
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
            region_df.to_excel(writer, index=False)
        st.download_button("📈 Download Region Names (.xlsx)", excel_buffer.getvalue(), file_name="region_names.xlsx")
    else:
        st.warning("No 'name' column found in the GeoJSON file.")

st.sidebar.header("2. Upload Excel Data")
excel_file = st.sidebar.file_uploader("Upload Excel File", type=["xlsx", "xls"])
output_files = []

if excel_file and selected_map_file != "-- Upload New Map --":
    excel_data = pd.ExcelFile(excel_file)
    df = excel_data.parse(sheet_name=excel_data.sheet_names[0])
    legend_df = excel_data.parse(sheet_name="Legend")
    legend_df.columns = legend_df.columns.str.lower()

    st.sidebar.header("3. Select Region Columns")
    region_col_excel = st.sidebar.selectbox("Excel region column", df.columns)
    region_col_geojson = st.sidebar.selectbox("GeoJSON region column", geo_data.columns, index=geo_data.columns.get_loc("name") if "name" in geo_data.columns else 0)

    st.sidebar.header("4. Select Categories to Label")
    categories = legend_df["category"].dropna().unique().tolist()
    selected_categories = st.sidebar.multiselect("Categories to display labels", categories, default=categories)
    selected_colors = legend_df[legend_df["category"].isin(selected_categories)]["color"].tolist()

    st.sidebar.header("5. Legend Settings")
    legend_position = st.sidebar.selectbox("Legend Position", ["upper left", "upper right", "lower left", "lower right"])
    legend_outside = st.sidebar.checkbox("Place legend outside map", value=True)

    st.sidebar.header("6. Filter & Compare")
    metric_cols_all = [col for col in df.columns if col != region_col_excel]
    selected_metrics = st.sidebar.multiselect("Select metrics to visualize", metric_cols_all, default=metric_cols_all[:1])
    value_filter = st.sidebar.slider("Minimum value threshold", float(df[metric_cols_all[0]].min()), float(df[metric_cols_all[0]].max()), float(df[metric_cols_all[0]].min()))

    map_type = st.sidebar.radio("Map Type", ["Interactive (HTML)", "Static (PNG)"])

    if st.sidebar.button("Generate Maps"):
        with st.spinner("Generating maps..."):
            merged = geo_data.merge(df, left_on=region_col_geojson, right_on=region_col_excel, how="left")
            merged["centroid"] = merged.geometry.centroid
            center_lat = merged["centroid"].y.mean()
            center_lon = merged["centroid"].x.mean()

            report_rows = []

            for metric_col in selected_metrics:
                merged_filtered = merged[merged[metric_col] >= value_filter].copy()
                merged_filtered["color"] = "gray"

                for _, row in legend_df.iterrows():
                    if row["column"] == metric_col:
                        condition = (merged_filtered[metric_col] >= row["min"]) & (merged_filtered[metric_col] <= row["max"])
                        merged_filtered.loc[condition, "color"] = row["color"]

                fig, ax = plt.subplots(figsize=(12, 9))
                merged_proj = merged_filtered.to_crs(epsg=3857)
                merged_proj.plot(color=merged_proj["color"], linewidth=0.8, edgecolor='black', ax=ax)
                for geom, label, color in zip(merged_proj.geometry, merged_proj[region_col_geojson], merged_proj["color"]):
                    centroid = geom.centroid
                    if color in selected_colors:
                        ax.text(centroid.x, centroid.y, label, fontsize=8, ha='center', color='black')

                ax.set_title(f"{metric_col} - Static Map")
                if legend_outside:
                    ax.legend(title=metric_col, loc=legend_position, bbox_to_anchor=(1.02, 1))
                else:
                    ax.legend(title=metric_col, loc=legend_position)
                st.subheader(f"{metric_col} - Static Map")
                st.pyplot(fig)

                png_path = f"{metric_col}_static_map.png"
                fig.savefig(png_path, bbox_inches='tight')
                with open(png_path, "rb") as f:
                    st.download_button(f"📅 Download {metric_col} Static PNG Map", f.read(), file_name=png_path, mime="image/png")
                output_files.append(png_path)

                report_rows.append({
                    "Metric": metric_col,
                    "Regions (Filtered)": merged_filtered.shape[0],
                    "Min": merged_filtered[metric_col].min(),
                    "Mean": round(merged_filtered[metric_col].mean(), 2),
                    "Max": merged_filtered[metric_col].max()
                })

        if report_rows:
            st.subheader("📊 Summary Report")
            report_df = pd.DataFrame(report_rows)
            st.dataframe(report_df)

            report_excel = io.BytesIO()
            with pd.ExcelWriter(report_excel, engine="xlsxwriter") as writer:
                report_df.to_excel(writer, sheet_name="Summary", index=False)
                workbook = writer.book
                for metric_col in report_df["Metric"]:
                    img_path = f"{metric_col}_static_map.png"
                    if os.path.exists(img_path):
                        worksheet = workbook.add_worksheet(f"Map_{metric_col[:28]}")
                        worksheet.insert_image("B2", img_path)

            st.download_button("📘 Download Summary Report (Excel)", report_excel.getvalue(), file_name="summary_report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            st.subheader("🧮 Metric Comparison Table")
            comparison_data = []
            for metric in selected_metrics:
                values = merged[[region_col_geojson, metric]].dropna()
                values = values[values[metric] >= value_filter]
                comparison_data.append(values.set_index(region_col_geojson)[metric])

            if comparison_data:
                comparison_df = pd.concat(comparison_data, axis=1)
                comparison_df.columns = selected_metrics
                st.dataframe(comparison_df)

            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.cell(200, 10, txt="Summary Report", ln=True, align='C')

            for idx, row in report_df.iterrows():
                pdf.ln(10)
                pdf.set_font("Arial", size=10)
                pdf.cell(0, 10, f"Metric: {row['Metric']} | Regions: {row['Regions (Filtered)']} | Min: {row['Min']} | Mean: {row['Mean']} | Max: {row['Max']}", ln=True)

            for metric in selected_metrics:
                img_path = f"{metric}_static_map.png"
                if os.path.exists(img_path):
                    pdf.add_page()
                    pdf.set_font("Arial", size=12)
                    pdf.cell(200, 10, txt=f"Map: {metric}", ln=True, align='L')
                    pdf.image(img_path, x=10, y=25, w=180)

            pdf_path = "summary_report.pdf"
            pdf.output(pdf_path)
            with open(pdf_path, "rb") as f:
                st.download_button("📄 Download Summary Report (PDF)", f.read(), file_name=pdf_path, mime="application/pdf")

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zipf:
            for file_path in output_files:
                zipf.write(file_path, os.path.basename(file_path))
        st.download_button("📦 Download All Maps as ZIP", zip_buffer.getvalue(), file_name="all_maps.zip", mime="application/zip")
