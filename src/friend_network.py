import json
from typing import Dict, Optional

from matplotlib import cm
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

from src.friend import Friend
from src.friend_set import FriendSet


class FriendNetwork(object):
    def __init__(self, friends: Optional[FriendSet] = None, common_friends: Dict[str, FriendSet] = None):
        self.friends = friends or FriendSet([])
        self.common_friends = common_friends or FriendSet([])

        self.node_positions = None
        self.graph = nx.Graph()

        if friends is not None and common_friends is not None:
            self.calculate_graph()

    def get_person_friends(self, **person_attributes) -> FriendSet:
        person = self.friends.filter(**person_attributes)
        edges = self.graph.edges(person.user_id)
        return FriendSet([
            self.friends.filter(user_id=contact)
            for _, contact in edges
        ])

    def get_person_friend_names(self, **attributes):
        friends = self.get_person_friends(**attributes)
        return friends.name

    def load_network(self, filename):
        with open(filename, "r", encoding="utf-8") as file:
            network = json.load(file)

        self.friends = FriendSet([
            Friend(**friend_dict)
            for friend_dict in network["friend_list"]
        ])

        common_friends = {}
        for friend_id, common_friends_dicts in network["common_friends"].items():
            common_friends[friend_id] = FriendSet([Friend(**friend_dict) for friend_dict in common_friends_dicts])

        self.common_friends = common_friends

        self.calculate_graph()
        self.compute_positions()

    def calculate_graph(self):
        self.graph = nx.Graph()
        self.graph.add_nodes_from([(friend.user_id, dict(name=friend.name)) for friend in self.friends])
        self.graph.add_edges_from(self._get_network_edges())
        self.compute_positions()

    def _get_network_edges(self):
        friends_info = self.get_friends_info()

        edges = []
        for friend_id, common_friends in self.common_friends.items():
            edges += [(
                friend_id,
                friends_info.iloc[(friends_info["link"] == friend.link).idxmax()].user_id
            ) for friend in common_friends]

        return edges

    def get_friends_info(self):
        return pd.DataFrame([vars(friend) for friend in self.friends])

    def filter_biggest_component(self):
        biggest_component_nodes = max(nx.connected_components(self.graph), key=len)
        self.graph = self.graph.subgraph(biggest_component_nodes)
        self.compute_positions()

    def compute_positions(self, layout=nx.spring_layout):
        self.node_positions = layout(self.graph)

    def draw_graph(self, node_scores=None, node_communities=None, label_proportion=0.1):  # pragma: no cover
        def get_random_labels(p):
            labels = {}
            for userid, name in nx.get_node_attributes(self.graph, 'name').items():
                if np.random.binomial(1, p) == 1:
                    labels[userid] = name

            return labels

        fig, ax = plt.subplots(1, 1, figsize=(20, 20))

        color = None

        if node_scores is not None:
            node_scores_series = pd.Series(node_scores).loc[list(self.graph.nodes)]
            threshold_quantile = 1 - label_proportion
            nodes_with_score_higher_than_threshold = node_scores_series[
                node_scores_series >= node_scores_series.quantile(threshold_quantile)
            ].index
            labels = {
                node: self.graph.nodes[node]["name"]
                for node in nodes_with_score_higher_than_threshold
            }
            color = node_scores
        else:
            labels = get_random_labels(label_proportion)
            if node_communities is not None:
                node_communities = pd.Series(node_communities)
                color = cm.get_cmap('Paired')(node_communities.loc[list(self.graph.nodes)])

        return nx.draw(
            self.graph,
            pos=self.node_positions,
            node_size=45,
            node_color=color,
            edge_color=(0, 0, 0, 0.1),
            ax=ax,
            with_labels=True,
            labels=labels
        )
