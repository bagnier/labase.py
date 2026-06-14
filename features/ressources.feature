# language: fr
Fonctionnalité: Trouver des ressources d'aide

  Une apprenante trouve des ressources afin de trouver de l'aide sur ses difficultés

  Contexte:
    Étant donné le paquet "débuter Python" à la resource "https://docs.python.org/fr/3/tutorial/index.html" est constitué des cartes suivantes :
      | ID    | Question                                           | Réponse                       | Ressource                                                                            |
      | PY001 | Comment déclare-t-on une variable en Python ?      | nom_variable = valeur         | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | PY002 | Quelle est la syntaxe d'une boucle for en Python ? | for element in sequence:      | https://docs.python.org/fr/3/tutorial/controlflow.html#for-statements                |
      | PY003 | Comment définit-on une fonction en Python ?        | def nom_fonction(paramètres): | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | PY004 | Comment importer un module en Python ?             | import nom_du_module          | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | PY005 | Comment écrit-on un commentaire en Python ?        | # Ceci est un commentaire     |                                                                                      |
    Et le paquet "Python avancé" à la resource "https://docs.python.org/fr/3/reference/index.html" est constitué des cartes suivantes :
      | ID    | Question                               | Réponse          | Ressource                                                 |
      | PYA01 | Qu'est-ce qu'un décorateur en Python ? | @nom_decorateur  | https://docs.python.org/fr/3/glossary.html#term-decorator |
      | PYA02 | Comment définir une classe en Python ? | class NomClasse: | https://docs.python.org/fr/3/tutorial/classes.html        |
    Et "Alice" veut apprendre le paquet "débuter Python"

  Scénario: Les ressources sont proposées pour toutes les cartes qui n'ont pas encore été étudiées
    Quand "Alice" regarde les ressources à revoir
    Alors "Alice" voit les ressources dans cet ordre:
      | Paquet         | Ressources                                                                           |
      | débuter Python | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | débuter Python | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | débuter Python | https://docs.python.org/fr/3/tutorial/controlflow.html#for-statements                |

  Scénario: Aucune ressource n'est proposée si aucune carte n'est marquée à revoir
    Étant donné que "Alice" a déjà revue les cartes du paquet "débuter Python" au niveau 3 il y a 10 jours
    Et "Alice" commence une session de révision
    Et "Alice" marque toutes les cartes du jour comme apprises
    Quand "Alice" regarde les ressources à revoir
    Alors "Alice" ne voit aucune ressource

  Scénario: Les ressources des cartes marquées à revoir sont proposées en fin de session
    Étant donné que "Alice" a déjà revue les cartes du paquet "débuter Python" au niveau 3 il y a 10 jours
    Et "Alice" commence une session de révision
    Et "Alice" marque la carte "PY001" comme à revoir
    Et "Alice" marque la carte "PY002" comme à revoir
    Et "Alice" marque la carte "PY003" comme apprise
    Quand "Alice" regarde les ressources à revoir
    Alors "Alice" voit les ressources dans cet ordre:
      | Paquet         | Ressources                                                                           |
      | débuter Python | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | débuter Python | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | débuter Python | https://docs.python.org/fr/3/tutorial/controlflow.html#for-statements                |

  Scénario: Les ressources sont présentées sans doublon
    Étant donné que "Alice" a déjà revue les cartes du paquet "débuter Python" au niveau 3 il y a 10 jours
    Et "Alice" commence une session de révision
    Et "Alice" marque la carte "PY001" comme à revoir
    Et "Alice" marque la carte "PY002" comme apprise
    Et "Alice" marque la carte "PY003" comme à revoir
    Quand "Alice" regarde les ressources à revoir
    Alors "Alice" voit les ressources dans cet ordre:
      | Paquet         | Ressources                                                                           |
      | débuter Python | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | débuter Python | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |

  Scénario: La ressource de carte n'est pas affichée si elle est identique à la ressource du paquet
    Étant donné que "Alice" a déjà revue les cartes du paquet "débuter Python" au niveau 3 il y a 10 jours
    Et "Alice" commence une session de révision
    Et "Alice" marque la carte "PY001" comme apprise
    Et "Alice" marque la carte "PY002" comme apprise
    Et "Alice" marque la carte "PY003" comme apprise
    Et "Alice" marque la carte "PY004" comme à revoir
    Quand "Alice" regarde les ressources à revoir
    Alors "Alice" voit les ressources dans cet ordre:
      | Paquet         | Ressources                                       |
      | débuter Python | https://docs.python.org/fr/3/tutorial/index.html |

  Scénario: des cartes sans ressource n'affichent rien de plus
    Étant donné que "Alice" a déjà revue les cartes du paquet "débuter Python" au niveau 3 il y a 10 jours
    Et "Alice" commence une session de révision
    Et "Alice" marque la carte "PY001" comme à revoir
    Et "Alice" marque la carte "PY002" comme apprise
    Et "Alice" marque la carte "PY003" comme apprise
    Et "Alice" marque la carte "PY004" comme apprise
    Et "Alice" marque la carte "PY005" comme à revoir
    Quand "Alice" regarde les ressources à revoir
    Alors "Alice" voit les ressources dans cet ordre:
      | Paquet         | Ressources                                                                           |
      | débuter Python | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | débuter Python | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |

  Scénario: les ressources sont cumulées durant les multiples sessions d'une journée
    Étant donné que "Alice" a déjà revue les cartes du paquet "débuter Python" au niveau 3 il y a 10 jours
    Et "Alice" commence une session de révision
    Et "Alice" marque la carte "PY001" comme à revoir
    Et "Alice" commence une session de révision
    Et "Alice" marque la carte "PY002" comme à revoir
    Quand "Alice" regarde les ressources à revoir
    Alors "Alice" voit les ressources dans cet ordre:
      | Paquet         | Ressources                                                                           |
      | débuter Python | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | débuter Python | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | débuter Python | https://docs.python.org/fr/3/tutorial/controlflow.html#for-statements                |

  Scénario: on voit les ressources de sa dernière journée de révision
    Étant donné que "Alice" a déjà revue les cartes du paquet "débuter Python" au niveau 3 il y a 10 jours
    Et "Alice" commence une session de révision
    Et "Alice" marque la carte "PY001" comme à revoir
    Et un jour passe
    Quand "Alice" regarde les ressources à revoir
    Alors "Alice" voit les ressources dans cet ordre:
      | Paquet         | Ressources                                                                           |
      | débuter Python | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | débuter Python | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |

  Scénario: les ressources de plusieurs paquets sont présentées groupées par paquet
    Étant donné que "Alice" a déjà revue les cartes du paquet "débuter Python" au niveau 3 il y a 10 jours
    Et "Alice" veut apprendre le paquet "Python avancé"
    Et "Alice" commence une session de révision
    Et "Alice" marque la carte "PYA01" comme à revoir
    Et "Alice" marque la carte "PYA02" comme apprise
    Et "Alice" marque la carte "PY001" comme à revoir
    Et "Alice" marque la carte "PY002" comme apprise
    Et "Alice" marque la carte "PY003" comme apprise
    Et "Alice" marque la carte "PY004" comme apprise
    Et "Alice" marque la carte "PY005" comme apprise
    Quand "Alice" regarde les ressources à revoir
    Alors "Alice" voit les ressources dans cet ordre:
      | Paquet         | Ressources                                                                           |
      | débuter Python | https://docs.python.org/fr/3/tutorial/index.html                                     |
      | débuter Python | https://docs.python.org/fr/3/tutorial/introduction.html#using-python-as-a-calculator |
      | Python avancé  | https://docs.python.org/fr/3/reference/index.html                                    |
      | Python avancé  | https://docs.python.org/fr/3/glossary.html#term-decorator                            |
      | Python avancé  | https://docs.python.org/fr/3/tutorial/classes.html                                   |
