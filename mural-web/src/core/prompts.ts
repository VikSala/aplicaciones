import type { ConversationTheme } from './types.ts';

export const BASE_PEDAGOGICAL_RULES = `
Actúa como un compañero de aprendizaje de idiomas conversacional, natural y empático.

Reglas pedagógicas:
1. Mantén la conversación principalmente en el idioma que está aprendiendo el usuario.
2. Corrige de forma suave: si hay un error, reformula correctamente dentro de tu respuesta sin convertir cada turno en una lección.
3. Prioriza que el usuario hable: responde de forma concisa, normalmente en 2-3 frases.
4. Mantén el contexto del tema seleccionado y usa situaciones realistas.
5. Haz preguntas naturales que permitan continuar la conversación.
6. Usa únicamente el progreso, vocabulario o errores anteriores que la aplicación incluya explícitamente en la memoria pedagógica; no inventes recuerdos ni nivel.
7. Si el usuario pide explícitamente una explicación, puedes salir temporalmente del formato conversacional para explicarla con claridad.
8. Cuando no se solicite un formato especial, usa texto fácil de pronunciar en voz alta: evita Markdown innecesario, listas largas, URLs y símbolos que suenen mal al sintetizarse.
`.trim();

export const CONVERSATION_THEMES: ConversationTheme[] = [
  { id: 1, title: 'Presentaciones y Saludos', description: 'Romper el hielo y hablar sobre quién eres.', culturalContext: 'Formas formales e informales de saludar según el país.' },
  { id: 2, title: 'Familia y Amigos', description: 'Describir el círculo cercano y relaciones.', culturalContext: 'Importancia de la familia en diferentes culturas.' },
  { id: 3, title: 'Rutina Diaria', description: 'Contar el día a día, horarios y costumbres.', culturalContext: 'Diferencias en los horarios de comidas y trabajo.' },
  { id: 4, title: 'Hobbies y Tiempo Libre', description: 'Aficiones, deportes y ocio.', culturalContext: 'Actividades de ocio populares.' },
  { id: 5, title: 'Comida y Restaurantes', description: 'Pedir en un local, gustos culinarios y recetas.', culturalContext: 'Costumbres gastronómicas locales y propinas.' },
  { id: 6, title: 'Viajes y Vacaciones', description: 'Experiencias viajeras, anécdotas y planes.', culturalContext: 'Destinos turísticos y etiqueta de viaje.' },
  { id: 7, title: 'Trabajo y Profesión', description: 'Entornos laborales, reuniones y proyectos.', culturalContext: 'Cultura corporativa y networking.' },
  { id: 8, title: 'Estudios y Educación', description: 'Experiencias académicas y aprendizaje.', culturalContext: 'Sistemas educativos y formación continua.' },
  { id: 9, title: 'Vivienda y Hogar', description: 'Describir la casa, el barrio y mudanzas.', culturalContext: 'Tipos de vivienda urbana vs. rural.' },
  { id: 10, title: 'Compras y Moda', description: 'Adquisiciones, tallas, precios y estilo.', culturalContext: 'Tendencias de consumo y mercados locales.' },
  { id: 11, title: 'Salud y Bienestar', description: 'Cuidado personal, deporte y visitas médicas.', culturalContext: 'Hábitos de vida saludable.' },
  { id: 12, title: 'Tecnología y Redes', description: 'Uso de apps, dispositivos e Internet.', culturalContext: 'Impacto digital en la sociedad moderna.' },
  { id: 13, title: 'Clima y Naturaleza', description: 'El tiempo atmosférico y ecología.', culturalContext: 'Conversaciones casuales sobre el clima.' },
  { id: 14, title: 'Arte y Cultura', description: 'Cine, literatura, música y teatro.', culturalContext: 'Movimientos culturales y referentes.' },
  { id: 15, title: 'Cine y Series', description: 'Argumentos, actores y preferencias de streaming.', culturalContext: 'Fenómenos de la cultura pop.' },
  { id: 16, title: 'Música y Conciertos', description: 'Estilos musicales, instrumentos y eventos.', culturalContext: 'Festivales y evolución musical.' },
  { id: 17, title: 'Deportes y Competición', description: 'Prácticas deportivas y eventos globales.', culturalContext: 'Pasión por los deportes de masas.' },
  { id: 18, title: 'Ciencia y Espacio', description: 'Descubrimientos, física y astronomía.', culturalContext: 'Divulgación científica actual.' },
  { id: 19, title: 'Historia y Tradiciones', description: 'Hechos pasados, mitos y festividades.', culturalContext: 'Costumbres históricas locales.' },
  { id: 20, title: 'Economía y Finanzas', description: 'Ahorro, compras inteligentes y dinero.', culturalContext: 'Gestión financiera personal.' },
  { id: 21, title: 'Filosofía y Opiniones', description: 'Debates abiertos sobre dilemas morales.', culturalContext: 'Formas de pensar y perspectivas.' },
  { id: 22, title: 'Animales y Mascotas', description: 'Cuidado de animales y fauna urbana.', culturalContext: 'El papel de las mascotas en el hogar.' },
  { id: 23, title: 'Ciudad y Transporte', description: 'Moverse en metro, bus, coche o a pie.', culturalContext: 'Sistemas de movilidad urbana.' },
  { id: 24, title: 'Futuro y Metas', description: 'Planes a largo plazo, sueños y proyectos.', culturalContext: 'Expectativas de crecimiento personal.' },
  { id: 25, title: 'Entrevista informática', description: 'Tú eres el entrevistador y el usuario es el aspirante.', culturalContext: 'Entrevista profesional informática.' },
  { id: 26, title: 'Clase de informática', description: 'El asistente actúa como profesor y el usuario como estudiante.', culturalContext: 'Clase práctica de informática.' },
];
