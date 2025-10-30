import streamlit as st
import geopandas as gpd
import folium
from streamlit_folium import st_folium
import io
import branca.colormap as cm

# --- CONFIGURATION ---
DN_TO_LULC_MAP = {
    1: 'Water',
    2: 'Tree Cover',
    4: 'Flooded Vegetation',
    5: 'Agriculture',
    7: 'Built Area',
    8: 'Bare Ground',
    11: 'Rangeland'
}

# --- HELPER FUNCTIONS ---

def process_data(uploaded_file, dn_map):
    """
    Reads an uploaded GeoJSON file, dissolves it by 'DN', and returns
    the original and dissolved GeoDataFrames.
    """
    status = st.status("Starting process...", expanded=True)
    try:
        status.update(label="Reading input GeoJSON file...")
        # Read the uploaded file object directly
        gdf = gpd.read_file(uploaded_file)

        # Check if the 'DN' column exists
        if 'DN' not in gdf.columns:
            status.error("Error: The GeoJSON file must contain a 'DN' property.")
            return None, None

        status.update(label="Dissolving polygons by land use type (DN)...")
        dissolved_gdf = gdf.dissolve(by='DN')

        status.update(label="Mapping land use classes...")
        # Add a human-readable 'land_use' column
        dissolved_gdf['land_use'] = dissolved_gdf.index.map(dn_map).fillna('Unknown')
        
        # Reset the index to turn 'DN' back into a regular column
        dissolved_gdf.reset_index(inplace=True)

        status.update(label="Reprojecting to standard WGS 84 (EPSG:4326)...")
        dissolved_gdf = dissolved_gdf.to_crs("EPSG:4326")
        
        status.success("Processing complete!")
        return gdf, dissolved_gdf

    except Exception as e:
        status.error(f"An unexpected error occurred: {e}")
        return None, None

def create_map(gdf):
    """
    Creates a Folium map with colored polygons based on 'land_use'.
    Returns the map object and the color mapping.
    """
    if gdf.empty:
        st.warning("No data to display on map.")
        return None, {}

    # Calculate the center of the map
    try:
        # Use unary_union to get a single geometry, then find its centroid
        center = gdf.geometry.unary_union.centroid
        map_center = [center.y, center.x]
        
        # Calculate appropriate zoom from total bounds
        min_lon, min_lat, max_lon, max_lat = gdf.total_bounds
        zoom = 10
        
        # Simple heuristic for zoom. Can be improved.
        lon_diff = max_lon - min_lon
        lat_diff = max_lat - min_lat
        if lon_diff > 0 and lat_diff > 0:
             # Fit map to bounds
             m = folium.Map(tiles="CartoDB positron")
             m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])
        else:
             m = folium.Map(location=map_center, zoom_start=zoom, tiles="CartoDB positron")
            
    except Exception as e:
        st.warning(f"Could not calculate map center/zoom: {e}. Defaulting view.")
        map_center = [0, 0] # Default center
        zoom = 2
        m = folium.Map(location=map_center, zoom_start=zoom, tiles="CartoDB positron")


    # --- Create a color map for the land use classes ---
    categories = sorted(gdf['land_use'].unique())
    # Use a color-blind friendly palette if available, or a standard one
    if len(categories) <= 8:
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']
    else:
        # Fallback for more categories
        color_scale = cm.linear.Set1_09.scale(0, len(categories))
        colors = [color_scale(i) for i in range(len(categories))]
        
    color_map = {category: color for category, color in zip(categories, colors)}
    
    # Style function to color polygons
    style_function = lambda x: {
        'fillColor': color_map.get(x['properties']['land_use'], '#808080'), # Default to gray
        'color': 'black',
        'weight': 1.0,
        'fillOpacity': 0.7
    }

    # Add data to map
    folium.GeoJson(
        gdf,
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=['land_use', 'DN'],
            aliases=['Land Use:', 'Class ID (DN):'],
            sticky=True
        )
    ).add_to(m)

    # --- REMOVED LEGEND FROM HERE ---
    # The legend is now created in the main app body.
    
    # Return both the map and the color_map for the legend
    return m, color_map

# --- STREAMLIT APP LAYOUT ---

st.set_page_config(layout="wide")
st.title("🗺️ Interactive GeoJSON Dissolver")
st.markdown("Upload a GeoJSON file to merge (dissolve) polygons based on a classification property (DN).")

# --- SIDEBAR for Inputs ---
with st.sidebar:
    st.header("⚙️ Controls")
    
    uploaded_file = st.file_uploader("1. Upload your GeoJSON file", type=["geojson", "json"])
    
    output_filename = st.text_input("2. Name your output file", "dissolved_land_use.geojson")
    
    process_button = st.button("3. Process File", type="primary", use_container_width=True)

    with st.expander("About & Class Mappings", expanded=False):
        st.info(
            """
            This app uses GeoPandas to perform a `dissolve` operation, 
            which is similar to 'Merge' in ArcGIS or 'Dissolve' in QGIS. 
            It merges geometries that share the same value in a specified field (in this case, 'DN').
            """
        )
        st.json(DN_TO_LULC_MAP, expanded=False)

# --- MAIN PAGE for Outputs ---
if process_button and uploaded_file is not None:
    # Run the main processing function
    original_gdf, dissolved_gdf = process_data(uploaded_file, DN_TO_LULC_MAP)
    
    if original_gdf is not None and dissolved_gdf is not None:
        st.header("📊 Summary")
        col1, col2 = st.columns(2)
        col1.metric("Original Features", len(original_gdf))
        col2.metric("Dissolved Features", len(dissolved_gdf))
        
        st.header("🗺️ Map of Dissolved Features")
        st.info("Hover over a polygon to see its land use class.")
        
        # --- MODIFIED MAP & LEGEND RENDERING ---
        
        # 1. Create map and get color map for legend
        map_object, color_mapping = create_map(dissolved_gdf)
        
        if map_object:
            # 2. Display the map
            st_folium(map_object, use_column_width=True, height=500)

            # 3. Display the legend *outside* the map using st.markdown
            if color_mapping:
                st.subheader("Legend")
                legend_html_parts = ['<div style="display: flex; flex-direction: column; gap: 5px;">']
                for category, color in color_mapping.items():
                    legend_html_parts.append(
                        f'<div><span style="background-color:{color}; width:20px; height:20px; display:inline-block; margin-right:5px; border: 1px solid black; opacity: 0.7; vertical-align: middle;"></span>'
                        f'<span style="vertical-align: middle;">{category}</span></div>'
                    )
                legend_html_parts.append('</div>')
                st.markdown("".join(legend_html_parts), unsafe_allow_html=True)
        
        st.header("📥 Download Result")
        # Convert dissolved GeoDataFrame to a string for download
        try:
            output_geojson_str = dissolved_gdf.to_json()
            st.download_button(
                label="Download Dissolved GeoJSON",
                data=output_geojson_str,
                file_name=output_filename,
                mime="application/json"
            )
        except Exception as e:
            st.error(f"Failed to prepare download file: {e}")

        st.header("📂 Dissolved Data Preview")
        # Show the data table (without the long 'geometry' column)
        st.dataframe(dissolved_gdf.drop(columns='geometry').head())
        
elif process_button and uploaded_file is None:
    st.warning("Please upload a GeoJSON file first.")

else:
    st.info("Upload a GeoJSON file and click 'Process File' to begin.")
