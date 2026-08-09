-- Active: 1785882812945@@localhost@5432@nhl
;WITH event_data AS (
    SELECT 
        game_id
        ,event_id
        ,type_code
        ,x_coord
        ,y_coord
        ,shot_type
        ,LAG(type_desc_key, 1, NULL) OVER (ORDER BY game_id, sort_order) AS previous_event
        ,LAG(shot_type, 1, NULL) OVER (ORDER BY game_id, sort_order) AS previous_shot_type
        ,LAG(reason, 1, NULL) OVER (ORDER BY game_id, sort_order) AS previous_miss_reason
        ,LAG(x_coord, 1, NULL) OVER (ORDER BY game_id, sort_order) AS previous_x_coord
        ,LAG(y_coord, 1, NULL) OVER (ORDER BY game_id, sort_order) AS precious_y_coord
        ,LAG(type_desc_key, 2, NULL) OVER (ORDER BY game_id, sort_order) AS previous_event_2
        ,LAG(shot_type, 2, NULL) OVER (ORDER BY game_id, sort_order) AS previous_shot_type_2
        ,LAG(reason, 2, NULL) OVER (ORDER BY game_id, sort_order) AS previous_miss_reason_2
        ,LAG(x_coord, 2, NULL) OVER (ORDER BY game_id, sort_order) AS previous_x_coord_2
        ,LAG(y_coord, 2, NULL) OVER (ORDER BY game_id, sort_order) AS precious_y_coord_2
        ,LAG(type_desc_key, 3, NULL) OVER (ORDER BY game_id, sort_order) AS previous_event_3
        ,LAG(shot_type, 3, NULL) OVER (ORDER BY game_id, sort_order) AS previous_shot_type_3
        ,LAG(reason, 3, NULL) OVER (ORDER BY game_id, sort_order) AS previous_miss_reason_3
        ,LAG(x_coord, 3, NULL) OVER (ORDER BY game_id, sort_order) AS previous_x_coord_3
        ,LAG(y_coord, 3, NULL) OVER (ORDER BY game_id, sort_order) AS precious_y_coord_3
    FROM playbyplay
    WHERE situation_code = '1551'
        AND period_type = 'REG'
)
SELECT *
FROM event_data
WHERE type_code IN (505, 506, 507, 508);