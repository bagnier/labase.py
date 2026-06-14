# language: fr
Fonctionnalité: apprentissage espacé

  une apprenante se voit proposé un apprentissage espacé afin de revoir périodiquement une notion

  La méthode de Leitner ne spécifie pas explicitement une procédure pour les journées de révision manquées.
  Cependant, en se basant sur les principes de la méthode et les pratiques courantes d'apprentissage espacé, voici ce qui est généralement recommandé :

  - Reprise immédiate : Dès que possible, reprendre les révisions en commençant par les cartes qui étaient dues le jour manqué.
  - Pas de pénalité : Ne pas pénaliser les cartes en les rétrogradant automatiquement. Le fait d'avoir manqué un jour ne signifie pas nécessairement que l'information a été oubliée.
  - Ajustement des dates : Décaler les dates de révision future pour les cartes non révisées, en les avançant d'un jour ou en les fixant au jour actuel.
  - Priorisation : Si le nombre de cartes à réviser devient trop important à cause du jour manqué, prioriser les cartes des niveaux inférieurs et celles qui n'ont pas été revues depuis le plus longtemps.
  - Flexibilité : Permettre à l'utilisateur de "rattraper" les révisions manquées sur plusieurs jours si nécessaire, plutôt que d'imposer de tout faire en une seule session.
  - Maintien de l'algorithme : Continuer à appliquer les règles normales de progression ou de régression des cartes basées sur les réponses de l'utilisateur, indépendamment du retard.

  règles supplémentaires ne faisant pas objet d'un scénario :
  - Les révisions ont lieu tous les jours, y compris les week-ends
  - Chaque carte est traitée de manière atomique lors d'une session interrompue

  Contexte:
    Étant donné le paquet "débuter Python" constitué des cartes suivantes :
      | ID    | Question                                                                     | Réponse                                                                                                    | Ressource                                                                                                 |
      | PY001 | Comment déclare-t-on une variable en Python ?                                | nom_variable = valeur                                                                                      | [Documentation Python](https://docs.python.org/3/tutorial/introduction.html#using-python-as-a-calculator) |
      | PY002 | Quelle est la syntaxe d'une boucle for en Python ?                           | for element in sequence:                                                                                   | [Boucles for](https://docs.python.org/3/tutorial/controlflow.html#for-statements)                         |
      | PY003 | Comment définit-on une fonction en Python ?                                  | def nom_fonction(paramètres):                                                                              | [Définir des fonctions](https://docs.python.org/3/tutorial/controlflow.html#defining-functions)           |
      | PY004 | Quel est l'opérateur pour la division entière en Python ?                    | //                                                                                                         | [Types numériques](https://docs.python.org/3/library/stdtypes.html#numeric-types-int-float-complex)       |
      | PY005 | Comment crée-t-on une liste en Python ?                                      | ma_liste = [element1, element2, element3]                                                                  | [Listes](https://docs.python.org/3/tutorial/introduction.html#lists)                                      |
      | PY006 | Quelle méthode utilise-t-on pour ajouter un élément à la fin d'une liste ?   | liste.append(element)                                                                                      | [Méthodes de liste](https://docs.python.org/3/tutorial/datastructures.html#more-on-lists)                 |
      | PY007 | Comment écrit-on un commentaire sur une seule ligne en Python ?              | # Ceci est un commentaire                                                                                  | [Commentaires](https://docs.python.org/3/tutorial/introduction.html#first-steps-towards-programming)      |
      | PY008 | Quelle est la syntaxe d'une structure conditionnelle if-else en Python ?     | if condition:<br>&nbsp;&nbsp;&nbsp;&nbsp;# code si vrai<br>else:<br>&nbsp;&nbsp;&nbsp;&nbsp;# code si faux | [Conditions if](https://docs.python.org/3/tutorial/controlflow.html#if-statements)                        |
      | PY009 | Comment crée-t-on un dictionnaire en Python ?                                | mon_dict = {"clé1": valeur1, "clé2": valeur2}                                                              | [Dictionnaires](https://docs.python.org/3/tutorial/datastructures.html#dictionaries)                      |
      | PY010 | Quelle fonction utilise-t-on pour lire l'entrée de l'utilisateur en Python ? | input()                                                                                                    | [Fonction input](https://docs.python.org/3/library/functions.html#input)                                  |
    Et la date du jour est le 01/09/2024
    Et "Alice" veut apprendre le paquet "débuter Python"

  Scénario: Toutes les cartes sont initialement de niveau 0
    Quand "Alice" commence une session de révision
    Alors "Alice" voit les cartes dans l'ordre suivant :
      | ID    | Niveau |
      | PY001 | 0      |
      | PY002 | 0      |
      | PY003 | 0      |
      | PY004 | 0      |
      | PY005 | 0      |
      | PY006 | 0      |
      | PY007 | 0      |
      | PY008 | 0      |
      | PY009 | 0      |
      | PY010 | 0      |

  Scénario: Seul le marquage des cartes importe lors d'une session interrompue
    Étant donné que "Alice" commence une session de révision
    Et "Alice" voit la carte "PY001" posant la question "Comment déclare-t-on une variable en Python ?"
    Et "Alice" marque la carte "PY001" comme à revoir
    Et "Alice" voit la carte "PY002" posant la question "Quelle est la syntaxe d'une boucle for en Python ?"
    Et un jour passe
    Et "Alice" commence une session de révision
    Alors "Alice" voit la carte "PY002" posant la question "Quelle est la syntaxe d'une boucle for en Python ?"

  Scénario: les carte à apprendre attendent l'apprenante
    Lorsque "Alice" regarde les cartes du jour
    Et "Alice" voit 10 cartes à apprendre
    Et 2 jours passent
    Et "Alice" regarde les cartes du jour
    Alors "Alice" voit 10 cartes à apprendre

  Scénario: les carte à apprendre reviennent avec le temps
    Étant donné que "Alice" regarde les cartes du jour
    Et "Alice" voit 10 cartes à apprendre
    Et "Alice" commence une session de révision
    Et "Alice" voit la carte "PY001" posant la question "Comment déclare-t-on une variable en Python ?"
    Et "Alice" marque la carte "PY001" comme apprise
    Et "Alice" voit 9 cartes à apprendre
    Lorsque 2 jours passent
    Alors "Alice" regarde les cartes du jour
    Et "Alice" voit 10 cartes à apprendre

  Scénario: le premier intervalle de révision est de 1 jour
    Étant donné que "Alice" commence une session de révision
    Et "Alice" voit la carte "PY001" posant la question "Comment déclare-t-on une variable en Python ?"
    Lorsque "Alice" marque la carte "PY001" comme apprise
    Et un jour passe
    Et "Alice" regarde les cartes du jour
    Alors "Alice" voit 10 cartes à apprendre

  Scénario: le second intervalle de révision est aussi de 1 jour
    Étant donné que "Alice" commence une session de révision
    Et "Alice" voit la carte "PY001" posant la question "Comment déclare-t-on une variable en Python ?"
    Lorsque "Alice" marque la carte "PY001" comme apprise
    Et un jour passe
    Et "Alice" commence une session de révision
    Et "Alice" voit la carte "PY002" posant la question "Quelle est la syntaxe d'une boucle for en Python ?"
    Lorsque "Alice" marque la carte "PY002" comme apprise
    Et un jour passe
    Et "Alice" regarde les cartes du jour
    Alors "Alice" voit 10 cartes à apprendre

  Plan du Scénario: les intervalles de révision sont les nombres de la suite de Fibonacci
    Étant donné que "Alice" a déjà revue la carte "PY001" au niveau <niveau_initial> il y a <jours_depuis_derniere_revision> jours
    Quand "Alice" commence une session de révision
    Et "Alice" marque la carte "PY001" comme apprise
    Alors la carte "PY001" est au niveau <nouveau_niveau>
    Et la dernière révision de "PY001" est fixée à aujourd'hui
    Et la prochaine révision de "PY001" est programmée dans <jours_jusqu_prochaine_revision> jours

    Exemples:
      | niveau_initial | jours_depuis_derniere_revision | nouveau_niveau | jours_jusqu_prochaine_revision |
      | 1              | 1                              | 2              | 1                              |
      | 2              | 1                              | 3              | 2                              |
      | 3              | 2                              | 4              | 3                              |
      | 4              | 3                              | 5              | 5                              |
      | 5              | 5                              | 6              | 8                              |
      | 6              | 8                              | 7              | 13                             |
      | 7              | 13                             | 8              | 21                             |
      | 8              | 21                             | 9              | 34                             |
      | 9              | 34                             | 9              | 34                             |

  Scénario: une révision incorrecte réinitialise le niveau à 1
    Étant donné que "Alice" a déjà revue les cartes du paquet "débuter Python" au niveau 4 il y a 60 jours
    Quand "Alice" commence une session de révision
    Quand "Alice" marque la carte "PY001" comme à revoir
    Alors la carte "PY001" est au niveau 1
    Et la dernière révision de "PY001" est fixée à aujourd'hui
    Et la prochaine révision de "PY001" est programmée dans 1 jours

  Scénario: une révision en retard n'affecte pas la progression si correcte
    Étant donné que "Alice" a déjà revue la carte "PY001" au niveau 3 il y a 5 jours
    Quand "Alice" commence une session de révision
    Quand "Alice" marque la carte "PY001" comme apprise
    Alors la carte "PY001" est au niveau 4
    Et la dernière révision de "PY001" est fixée à aujourd'hui
    Et la prochaine révision de "PY001" est programmée dans 3 jours

  Scénario: une révision mensuelle reste à ce niveau
    Étant donné que "Alice" a déjà revue la carte "PY001" au niveau 9 il y a 34 jours
    Quand "Alice" commence une session de révision
    Quand "Alice" marque la carte "PY001" comme apprise
    Alors la carte "PY001" est au niveau 9
    Et la dernière révision de "PY001" est fixée à aujourd'hui
    Et la prochaine révision de "PY001" est programmée dans 34 jours

  Scénario: une révision en retard calcule la prochaine date à partir du jour effectif de réponse
    Étant donné que "Alice" a déjà revue la carte "PY001" au niveau 3 il y a 60 jours
    Quand "Alice" commence une session de révision
    Quand "Alice" marque la carte "PY001" comme apprise
    Alors la carte "PY001" est au niveau 4
    Et la dernière révision de "PY001" est fixée à aujourd'hui
    Et la prochaine révision de "PY001" est programmée dans 3 jours

  Scénario: les cartes sont triées selon la prochaine révision la plus ancienne puis dans l'ordre du paquet
    Étant donné que "Alice" a déjà revue les cartes suivantes:
      | ID    | Niveau | Date de dernière révision |
      | PY001 | 1      | 14/07/2024                |
      | PY002 | 2      | 14/07/2024                |
      | PY003 | 3      | 14/07/2024                |
      | PY004 | 4      | 14/07/2024                |
      | PY005 | 5      | 14/07/2024                |
      | PY006 | 6      | 14/07/2024                |
      | PY007 | 7      | 14/07/2024                |
      | PY008 | 8      | 14/07/2024                |
      | PY009 | 9      | 14/07/2024                |
      | PY010 | 9      | 14/07/2024                |
    Quand "Alice" commence une session de révision
    Alors "Alice" voit les cartes dans l'ordre suivant :
      | ID    | Niveau |
      | PY001 | 1      |
      | PY002 | 2      |
      | PY003 | 3      |
      | PY004 | 4      |
      | PY005 | 5      |
      | PY006 | 6      |
      | PY007 | 7      |
      | PY008 | 8      |
      | PY009 | 9      |
      | PY010 | 9      |

  Scénario: Les cartes pas encore étudiées sont proposées en premier
    Étant donné que "Alice" a déjà revue les cartes suivantes:
      | ID    | Niveau | Date de dernière révision |
      | PY001 | 1      | 14/07/2024                |
      | PY002 | 2      | 14/07/2024                |
      | PY003 | 3      | 14/07/2024                |
      | PY004 | 4      | 14/07/2024                |
    Quand "Alice" commence une session de révision
    Alors "Alice" voit les cartes dans l'ordre suivant :
      | ID    | Niveau |
      | PY005 | 0      |
      | PY006 | 0      |
      | PY007 | 0      |
      | PY008 | 0      |
      | PY009 | 0      |
      | PY010 | 0      |
      | PY001 | 1      |
      | PY002 | 2      |
      | PY003 | 3      |
      | PY004 | 4      |

  Scénario: Les cartes de différents paquets sont mélangées
    Étant donné le paquet "Python avancé" constitué des cartes suivantes :
      | ID    | Question                               | Réponse          |
      | PYA01 | Qu'est-ce qu'un décorateur en Python ? | @nom_decorateur  |
      | PYA02 | Comment définir une classe en Python ? | class NomClasse: |
    Et "Alice" veut apprendre le paquet "Python avancé"
    Étant donné que "Alice" a déjà revue les cartes suivantes:
      | ID    | Niveau | Date de dernière révision |
      | PY001 | 3      | 14/07/2024                |
      | PY002 | 5      | 14/07/2024                |
      | PY003 | 1      | 14/07/2024                |
      | PYA01 | 4      | 14/07/2024                |
      | PYA02 | 2      | 14/07/2024                |
    Quand "Alice" commence une session de révision
    Alors "Alice" voit les cartes dans l'ordre suivant :
      | ID    | Niveau |
      | PY004 | 0      |
      | PY005 | 0      |
      | PY006 | 0      |
      | PY007 | 0      |
      | PY008 | 0      |
      | PY009 | 0      |
      | PY010 | 0      |
      | PY003 | 1      |
      | PYA02 | 2      |
      | PY001 | 3      |
      | PYA01 | 4      |
      | PY002 | 5      |

