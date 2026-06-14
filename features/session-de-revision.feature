# language: fr
Fonctionnalité: Session de révision

  Une apprenante interagit avec une carte de révision afin d'apprendre une nouvelle notion

  Les sessions de révision ont pour propos de présenter seulement une partie des cartes.
  Terminer la session de révision avant d'avoir marqué toutes les cartes laisse les cartes marquées ou non dans le même état.

  Contexte:
    Étant donné le paquet "débuter Python" constitué des cartes suivantes :
      | ID    | Question                                           | Réponse                       |
      | PY001 | Comment déclare-t-on une variable en Python ?      | nom_variable = valeur         |
      | PY002 | Quelle est la syntaxe d'une boucle for en Python ? | for element in sequence:      |
      | PY003 | Comment définit-on une fonction en Python ?        | def nom_fonction(paramètres): |
    Et "Alice" veut apprendre le paquet "débuter Python"

  Scénario: Un paquet à apprendre est entièrement accessible dès le début
    Lorsque "Alice" regarde les cartes du jour
    Alors "Alice" voit 3 cartes à apprendre

  Scénario: Un paquet à apprendre est personnel à chaque utilisateur
    Lorsque "Bob" regarde les cartes du jour
    Alors "Bob" ne voit pas de carte à apprendre

  Scénario: Les cartes sont présentées dans l'ordre des paquets
    Lorsque "Alice" commence une session de révision
    Alors "Alice" voit les cartes dans l'ordre suivant :
      | ID    | Niveau |
      | PY001 | 0      |
      | PY002 | 0      |
      | PY003 | 0      |

  Scénario: Les cartes sont présentées groupées par paquets
    Étant donné que le paquet "Python avancé" constitué des cartes suivantes :
      | ID    | Question                               | Réponse          |
      | PYA01 | Qu'est-ce qu'un décorateur en Python ? | @nom_décorateur  |
      | PYA02 | Comment définir une classe en Python ? | class NomClasse: |
    Et "Alice" veut apprendre le paquet "Python avancé"
    Et "Alice" regarde les cartes du jour
    Lorsque "Alice" commence une session de révision
    Alors "Alice" voit les cartes dans l'ordre suivant :
      | ID    | Niveau |
      | PY001 | 0      |
      | PY002 | 0      |
      | PY003 | 0      |
      | PYA01 | 0      |
      | PYA02 | 0      |

  Scénario: Une carte marquée comme apprise est retirée des cartes du jour
    Étant donné que "Alice" regarde les cartes du jour
    Et "Alice" commence une session de révision
    Lorsque "Alice" consulte la réponse de la carte "PY001" et voit "nom_variable = valeur"
    Et "Alice" marque la carte "PY001" comme apprise
    Alors "Alice" voit 2 cartes à apprendre
    Et "Alice" voit la carte "PY002" posant la question "Quelle est la syntaxe d'une boucle for en Python ?"

  Scénario: Une carte marquée à revoir est retirée des cartes du jour
    Étant donné que "Alice" regarde les cartes du jour
    Et "Alice" commence une session de révision
    Lorsque "Alice" consulte la réponse de la carte "PY001" et voit "nom_variable = valeur"
    Et "Alice" marque la carte "PY001" comme à revoir
    Alors "Alice" voit 2 cartes à apprendre
    Et "Alice" voit la carte "PY002" posant la question "Quelle est la syntaxe d'une boucle for en Python ?"

  Scénario: Une session de révision peut être interrompue sans conséquence
    Étant donné que "Alice" commence une session de révision
    Et "Alice" marque la carte "PY001" comme apprise
    Lorsque "Alice" commence une session de révision
    Alors "Alice" voit la carte "PY002" posant la question "Quelle est la syntaxe d'une boucle for en Python ?"
    