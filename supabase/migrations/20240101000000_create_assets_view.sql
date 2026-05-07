-- Create assets_view to join assets with all reference tables.
-- This view is queried by the FastAPI backend on the /assets and
-- /assets/{asset_id} endpoints, returning flattened asset data with
-- human-readable names instead of raw foreign-key IDs.

CREATE VIEW assets_view AS
SELECT a.*,
       c.name  AS category,
       d.name  AS department,
       ca.name AS campus,
       l.name  AS location,
       s.name  AS supplier,
       st.name AS status,
       co.name AS condition
FROM assets a
LEFT JOIN categories  c  ON a.category_id  = c.id
LEFT JOIN departments d  ON a.department_id = d.id
LEFT JOIN campuses    ca ON a.campus_id     = ca.id
LEFT JOIN locations   l  ON a.location_id   = l.id
LEFT JOIN suppliers   s  ON a.supplier_id   = s.id
LEFT JOIN statuses    st ON a.status_id     = st.id
LEFT JOIN conditions  co ON a.condition_id  = co.id;
