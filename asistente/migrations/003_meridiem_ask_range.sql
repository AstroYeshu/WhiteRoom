-- Rango de horas sin am/pm que el parser de fechas PREGUNTA en vez de adivinar (ambos extremos
-- incluidos). Por debajo se asume tarde (1-4) y por encima, mañana. 12 siempre es mediodía.
INSERT INTO settings (key, value) VALUES ('meridiem_ask_range', '5-11');
