-- =============================================================================
-- Script de creación de base de datos PostgreSQL para sistema LPR
-- =============================================================================
-- Este script crea la base de datos y la tabla para almacenar transmisiones
-- pendientes, exitosas y fallidas.
--
-- Ejecución:
--   1. Conectarse como superusuario: psql -U postgres
--   2. Ejecutar: \i create_postgres_db.sql
--   O ejecutar manualmente cada comando
-- =============================================================================

-- Crear base de datos (opcional - puede ejecutarse manualmente)
-- Descomentar si necesitas crear la base de datos desde este script
-- CREATE DATABASE radar_lpr_db;
-- \c radar_lpr_db;

-- =============================================================================
-- TABLA: transmissions
-- =============================================================================
-- Almacena las transmisiones de detecciones de placas, incluyendo:
-- - Transmisiones pendientes (status = FALSE)
-- - Transmisiones completadas (status = TRUE)
-- =============================================================================

CREATE TABLE IF NOT EXISTS transmissions (
    id SERIAL PRIMARY KEY,
    plate TEXT NOT NULL,
    detection_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    speed INTEGER,
    image_full_path TEXT,
    image_crop_path TEXT,
    remote_dir_full TEXT,
    remote_dir_crop TEXT,
    remote_filename_full TEXT,
    remote_filename_crop TEXT,
    status BOOLEAN NOT NULL DEFAULT FALSE,
    retry_count INTEGER DEFAULT 0,
    last_retry_time TIMESTAMP WITHOUT TIME ZONE,
    error_message TEXT,
    metadata TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
);

-- Comentarios en columnas para documentación
COMMENT ON TABLE transmissions IS 'Tabla de transmisiones de detecciones de placas';
COMMENT ON COLUMN transmissions.id IS 'Identificador único de la transmisión';
COMMENT ON COLUMN transmissions.plate IS 'Placa del vehículo detectado';
COMMENT ON COLUMN transmissions.detection_time IS 'Fecha y hora de la detección (TIMESTAMP WITHOUT TIME ZONE)';
COMMENT ON COLUMN transmissions.speed IS 'Velocidad del vehículo en km/h (nullable)';
COMMENT ON COLUMN transmissions.image_full_path IS 'Ruta local de la imagen completa (contexto/road)';
COMMENT ON COLUMN transmissions.image_crop_path IS 'Ruta local de la imagen recortada (placa)';
COMMENT ON COLUMN transmissions.remote_dir_full IS 'Directorio remoto para imagen completa';
COMMENT ON COLUMN transmissions.remote_dir_crop IS 'Directorio remoto para imagen recortada';
COMMENT ON COLUMN transmissions.remote_filename_full IS 'Nombre de archivo remoto para imagen completa';
COMMENT ON COLUMN transmissions.remote_filename_crop IS 'Nombre de archivo remoto para imagen recortada';
COMMENT ON COLUMN transmissions.status IS 'Estado de carga: FALSE = pendiente/no cargado, TRUE = cargado exitosamente';
COMMENT ON COLUMN transmissions.retry_count IS 'Número de intentos de transmisión realizados';
COMMENT ON COLUMN transmissions.last_retry_time IS 'Fecha y hora del último intento de reintento (TIMESTAMP)';
COMMENT ON COLUMN transmissions.error_message IS 'Mensaje de error si la transmisión falló';
COMMENT ON COLUMN transmissions.metadata IS 'Metadatos adicionales en formato JSON';
COMMENT ON COLUMN transmissions.created_at IS 'Fecha y hora de creación del registro (TIMESTAMP)';
COMMENT ON COLUMN transmissions.updated_at IS 'Fecha y hora de última actualización (TIMESTAMP)';

-- =============================================================================
-- ÍNDICES
-- =============================================================================
-- Índices para optimizar consultas frecuentes:
-- - Búsqueda por estado (pending, retry, success, failed)
-- - Búsqueda por tiempo de reintento (para determinar cuándo reintentar)
-- - Búsqueda por fecha de creación (para limpieza y ordenamiento)
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_status ON transmissions(status);
CREATE INDEX IF NOT EXISTS idx_retry_time ON transmissions(last_retry_time);
CREATE INDEX IF NOT EXISTS idx_created_at ON transmissions(created_at);

-- =============================================================================
-- VERIFICACIÓN
-- =============================================================================
-- Verificar que la tabla se creó correctamente:
-- SELECT * FROM information_schema.tables WHERE table_name = 'transmissions';
-- 
-- Verificar índices:
-- SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'transmissions';
-- =============================================================================
