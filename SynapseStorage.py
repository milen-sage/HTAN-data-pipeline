# allows specifying explicit variable types
from typing import Any, Dict, Optional, Text

# used to generate unique names for entities
import uuid

# json serialization lib
import json

# manipulation of dataframes 
import pandas as pd

# Python client for Synapse
import synapseclient

from synapseclient import File, Folder, Table
from synapseclient.table import build_table
import synapseutils

from utils import update_df
from schema_explorer import SchemaExplorer
import schema_generator as sg #TODO refactor so that we don't need to import schema generator here
from config import storage

class SynapseStorage(object):

    """Implementation of Storage interface for datasets/files stored on Synapse.
    Provides utilities to list files in a specific project; update files annotations, create fileviews, etc.
    TODO: Need to define the interface and rename and/or refactor some of the methods below.
    """


    def __init__(self,
                 syn: synapseclient = None,
                 token: str = None ## gets sessionToken for logging in
                 ) -> None:

        """Instantiates a SynapseStorage object

        Args:
            syn: synapse client; if not provided instantiate one
            token: if provided, use to instantiate a synapse client and login using the toke
            TODO: move away from specific project setup and work with an interface that Synapse specifies (e.g. based on schemas)
        """
     
        # login using a token 
        if token:
            self.syn = synapseclient.Synapse()
            self.syn.login(sessionToken = token)
        elif syn: # if no token, assume a logged in synapse client has been provided
            self.syn = syn

        self.storageFileview = storage["Synapse"]["masterFileview"]

        # get data in administrative fileview for this pipeline 
        self.setStorageFileviewTable()

        self.manifest = storage["Synapse"]["manifestFilename"]


    def setStorageFileviewTable(self) -> None:
        """ 
            Gets all data in an administrative fileview as a pandas dataframe and sets the SynapseStorage storageFileviewTable attribute
            Raises: TODO 
                ValueError: administrative fileview not found.
        """
        # query fileview for all administrative data
        self.storageFileviewTable = self.syn.tableQuery("SELECT * FROM " + self.storageFileview).asDataFrame()
   

    def getPaginatedRestResults(currentUserId : str) -> dict:
        """
            Gets the paginated results of the REST call to Synapse to check what projects the current user is part of.

            Args:
                currentUserId: synapse id for the user whose projects we want to get 
            
            Returns: a dictionary with a next page token and the results
        """
        all_results = syn.restGET('/projects/user/{principalId}'.format(principalId=currentUserId))
    
        while 'nextPageToken' in all_results: # iterate over next page token in results while there is any
            results_token = syn.restGET('/projects/user/{principalId}?nextPageToken={nextPageToken}'.format(principalId=currentUserId, nextPageToken = all_results['nextPageToken']))
            all_results['results'].extend(results_token['results'])

            if 'nextPageToken' in results_token:
                all_results['nextPageToken'] = results_token['nextPageToken']
            else:
                del(all_results['nextPageToken'])

        return all_results


    def getStorageProjects(self) -> list: 
    
        """ get all storage projects the current user has access to
        within the scope of the storage fileview parameter specified as SynapseStorage attribute

        Returns: a list of storage projects the current user has access to; the list consists of tuples (projectId, projectName) 
        """

        # get the set of all storage Synapse project accessible for this pipeline
        storageProjects = self.storageFileviewTable["projectId"].unique()

        # get the set of storage Synapse project accessible for this user

        # get current user ID
        currentUser = self.syn.getUserProfile()
        currentUserName = currentUser.userName 
        currentUserId = currentUser.ownerId
        
        # get a set of projects from Synapse 
        currentUserProjects = self.syn.restGET('/projects/user/{principalId}'.format(principalId=currentUserId))
        
        # prune results json filtering project id
        currentUserProjects = [currentUserProject["id"] for currentUserProject in currentUserProjects["results"]]

        # find set of user projects that are also in this pipeline's storage projects set
        storageProjects = list(set(storageProjects) & set(currentUserProjects))

        # prepare a return list of project IDs and names
        projects = []
        for projectId in storageProjects:
            projectName = self.syn.get(projectId, downloadFile = False).name
            projects.append((projectId, projectName))

        return projects


    def getStorageDatasetsInProject(self, projectId:str) -> list:
        
        """ get all datasets in folder under a given storage projects the current user has access to

        Args:
            projectId: synapse ID of a storage project
        Returns: a list of datasets within the given storage project; the list consists of tuples (datasetId, datasetName)
        Raises: TODO
            ValueError: Project ID not found.
        """
        
        # select all folders and their names w/in the storage project; if folder content type is define, only select folders that contain datasets
        areDatasets = False
        if "contentType" in self.storageFileviewTable.columns:
            foldersTable = self.storageFileviewTable[(self.storageFileviewTable["contentType"] == "dataset") & (self.storageFileviewTable["projectId"] == projectId)]
            areDatasets = True
        else:
            foldersTable = self.storageFileviewTable[(self.storageFileviewTable["type"] == "folder") & (self.storageFileviewTable["projectId"] == projectId)]


        # get an array of tuples (folderId, folderName)
        # some folders are part of datasets; others contain datasets
        # each dataset parent is the project; folders part of a dataset have another folder as a parent
        # to get folders if and only if they contain datasets for each folder 
        # check if folder's parent is the project; if so that folder contains a dataset,
        # unless the folder list has already been filtered to dataset folders based on contentType attribute above
        
        datasetList = []
        folderProperties = ["id", "name"]
        for folder in list(foldersTable[folderProperties].itertuples(index = False, name = None)):
            if self.syn.get(folder[0], downloadFile = False).properties["parentId"] == projectId or areDatasets:
                datasetList.append(folder)
        
        return datasetList


    def getFilesInStorageDataset(self, datasetId:str, fileNames:list = None) -> list:
        """ get all files in a given dataset folder 

        Args:
            datasetId: synapse ID of a storage dataset
            fileNames: get a list of files with particular names; defaults to None in which case all dataset files are returned (except bookkeeping files, e.g.
            metadata manifests); if fileNames is not None all files matching the names in the fileNames list are returned if present
        Returns: a list of files; the list consist of tuples (fileId, fileName)
        Raises: TODO
            ValueError: Dataset ID not found.
        """

        # select all files within a given storage dataset (top level folder in a Synapse storage project)
        filesTable = self.storageFileviewTable[(self.storageFileviewTable["type"] == "file") & (self.storageFileviewTable["parentId"] == datasetId)]

        # return an array of tuples (fileId, fileName)
        fileList = []
        for row in filesTable[["id", "name"]].itertuples(index = False, name = None): 
            #if not row[1] == self.manifest and not fileNames:
            if not "manifest" in row[1] and not fileNames:
                # check if a metadata-manifest file has been passed in the list of filenames; assuming the manifest file has a specific filename, e.g. synapse_storage_manifest.csv; remove the manifest filename if so; (no need to add metadata to the metadata container); TODO: expose manifest filename as a configurable parameter and don't hard code.
                fileList.append(row)

            elif not fileNames == None and row[1] in fileNames:
                # if fileNames is specified and file is in fileNames add it to the returned list
                fileList.append(row)

        return fileList
        

    def getDatasetManifest(self, datasetId:str) -> list:
        """ get the manifest associated with a given dataset 

        Args:
            datasetId: synapse ID of a storage dataset
        Returns: a tuple of manifest file ID and manifest name; (fileId, fileName); returns empty list if no manifest is found
        """

        # get a list of files containing the manifest for this dataset (if any)
        
        manifest = self.getFilesInStorageDataset(datasetId, fileNames = [self.manifest])
        
        if not manifest:
            return []
        else:
            return manifest[0] # extract manifest tuple from list

    
    def update_dataset_manifest_files(self, dataset_id:str) -> str:

        """ Fetch the names and entity IDs of all current files in dataset in store, if any; update dataset's manifest, if any; with new files, if any

        Args:
            dataset_id: synapse ID of a storage dataset
        Returns: synapse ID of updated manifest 
        """

        # get existing manifest Synapse ID
        manifest_id_name = self.getDatasetManifest(dataset_id)
        if not manifest_id_name:
            # no manifest exists yet: abort
            print("No manifest found in storage dataset " + dataset_id + "! Abort.")
            return ""

        manifest_id = manifest_id_name[0]
        manifest_filepath = self.syn.get(manifest_id).path
        manifest = pd.read_csv(manifest_filepath)

        # get current list of files
        dataset_files = self.getFilesInStorageDataset(dataset_id)
        
        # update manifest with additional filenames, if any;    
        # note that if there is an existing manifest and there are files in the dataset the columns Filename and entityId are assumed to be present in manifest schema
        # TODO: use idiomatic panda syntax
        if dataset_files:
            new_files = {
                    "Filename":[],
                    "entityId":[]
            }

            # find new files if any
            for file_id, file_name in dataset_files:
                if not file_id in manifest["entityId"].values:
                    new_files["Filename"].append(file_name)
                    new_files["entityId"].append(file_id)
            
            # update manifest so that it contain new files
            #manifest = pd.DataFrame(new_files)
            new_files = pd.DataFrame(new_files)
            manifest = pd.concat([new_files, manifest], sort = False).reset_index().drop("index", axis = 1)
            # update the manifest file, so that it contains the relevant entity IDs
            manifest.to_csv(manifest_filepath, index = False)

            # store manifest and update associated metadata with manifest on Synapse
            manifest_id = self.associateMetadataWithFiles(manifest_filepath, dataset_id)
            
        return manifest_id


    def getAllManifests(self) -> list:
        """ get all metadata manifest files across all datasets in projects a user has access to

        Returns: a list of projects, datasets per project and metadata manifest Synapse ID for each dataset
        as a list of tuples, one for each manifest:
                     [
                        (
                            (projectId, projectName),
                            (datasetId, dataName),
                            (manifestId, manifestName)
                        ),
                        ...
                     ]

        TODO: return manifest URI instead of Synapse ID for interoperability with other implementations of a store interface
        """
        
        projects = self.getStorageProjects()

        manifests = []
        for (projectId, projectName) in projects:

            datasets = self.getStorageDatasetsInProject(projectId)

            for (datasetId, datasetName) in datasets:

                # encode information about the manifest in a simple list (so that R clients can unpack it)
                # eventually can serialize differently
                manifest = (
                            (projectId, projectName),
                            (datasetId, datasetName),
                            self.getDatasetManifest(datasetId)
                )
                manifests.append(manifest)

        return manifests


    def associateMetadataWithFiles(self, metadataManifestPath:str, datasetId:str) -> str:
        """Associate metadata with files in a storage dataset already on Synapse. 
        Upload metadataManifest in the storage dataset folder on Synapse as well. Return synapseId of the uploaded manifest file.
        
            Args: 
                metadataManifestPath: path to csv containing a validated metadata manifest. The manifest should include a column entityId containing synapse IDs of files/entities to be associated with metadata, if that is applicable to the dataset type. Some datasets, e.g. clinical data, do not contain file id's, but data is stored in a table: one row per item. In this case, the system creates a file on Synapse for each row in the table (e.g. patient, biospecimen) and associates the columnset data as metadata/annotations to his file. 
                datasetId: synapse ID of folder containing the dataset
            Returns: synapse Id of the uploaded manifest
            Raises: TODO
                FileNotFoundException: Manifest file does not exist at provided path.

        """

        # determine dataset name
        datasetEntity = self.syn.get(datasetId, downloadFile = False)
        datasetName = datasetEntity.name
        datasetParentProject = datasetEntity.properties["parentId"]

        # read new manifest csv
        manifest = pd.read_csv(metadataManifestPath)

        # check if there is an existing manifest
        existingManifest = self.getDatasetManifest(datasetId)
        existingTableId = None

        if existingManifest:

            # update the existing manifest, so that existing entities get updated metadata and new entities are preserved; 
            # note that an existing manifest always contains an entityId column, which is assumed to be the index key
            # if updating an existing manifest the new manifest should also contain an entityId column 
            # (it is ok if the entities ID in the new manifest are blank)
            manifest['entityId'].fillna('', inplace = True)
            manifest = update_df(manifest, existingManifest, "entityId")

            # retrieve Synapse table associated with this manifest, so that it can be updated below
            existingTableId = self.syn.findEntityId(datasetName+"_table", datasetParentProject)
            
        # if this is a new manifest there could be no Synapse entities associated with the rows of this manifest
        # this may be due to data type (e.g. clinical data) being tabular 
        # and not requiring files; to utilize uniform interfaces downstream
        # (i.e. fileviews), a Synapse entity (a folder) is created for each row 
        # and an entity column is added to the manifest containing the resulting 
        # entity IDs; a table is also created at present as an additional interface 
        # for downstream query and interaction with the data. 
        
        if not "entityId" in manifest.columns:
            manifest["entityId"] = ""

        # get a schema explorer object to ensure schema attribute names used in manifest are translated to schema labels for synapse annotations
        se = SchemaExplorer()
        
        # iterate over manifest rows, create Synapse entities and store corresponding entity IDs in manifest if needed
        # also set metadata for each synapse entity as Synapse annotations
        for idx, row in manifest.iterrows():
            if not row["entityId"]:
               # no entity exists for this row
               # so create one
               rowEntity = Folder(str(uuid.uuid4()), parent=datasetId)
               rowEntity = self.syn.store(rowEntity)
               entityId = rowEntity["id"]
               row["entityId"] = entityId
               manifest.loc[idx, "entityId"] = entityId
            else:
               # get the entity id corresponding to this row
               entityId = row["entityId"]
            
            #  prepare metadata for Synapse storage (resolve display name into a name that Synapse annotations support (e.g no spaces)
            metadataSyn = {}
            for k, v in row.to_dict().items():
                keySyn = se.get_class_label_from_display_name(str(k))

                metadataSyn[keySyn] = v

            self.syn.setAnnotations(entityId, metadataSyn)

        # create/update a table corresponding to this dataset in this dataset's parent project

        if existingTableId:
            # if table already exists, delete it and upload the new table
            # TODO: do a proper Synapse table update
            self.syn.delete(existingTableId)
        
        # create table using latest manifest content
        table = build_table(datasetName + "_table", self.syn.get(datasetId, downloadFile = False).properties["parentId"], manifest)
        table = self.syn.store(table)
         
        # update the manifest file, so that it contains the relevant entity IDs
        manifest.to_csv(metadataManifestPath, index = False)

        # store manifest to Synapse
        manifestSynapseFile = File(metadataManifestPath, description = "Manifest for dataset " + datasetId, parent = datasetId)

        manifestSynapseFileId = self.syn.store(manifestSynapseFile).id

        return manifestSynapseFileId

    def get_data_preview(self, se:SchemaExplorer):
        """
            Get a preview of all data (both files and clinical) across all data storage projects the user has access to.
            Format the data in JSON according to the file here:
            TODO: link json file example

            Args:
                se: schema explorer object to get descriptions of attributes
        """

        projects = self.getStorageProjects()

        data_preview = {}
        for (project_id, project_name) in projects:

            datasets = self.getStorageDatasetsInProject(project_id)
            data_preview[project_name] = {}

            for (dataset_id, dataset_name) in datasets:

                entity = self.syn.get(dataset_id, downloadFile = False)
                dataset_annotations = entity.annotations
                print(dataset_annotations)
                if "dataType" in dataset_annotations and "Component" in dataset_annotations and "dataView" in dataset_annotations:
                    
                    data_type = dataset_annotations["dataType"][0]
                    component = dataset_annotations["Component"][0]
                    data_link = dataset_annotations["dataView"][0]
                    
                    manifest_id = self.getDatasetManifest(dataset_id)[0]
                    manifest_link = "https://www.synapse.org/#!Synapse:" + manifest_id

                    manifest_filepath = self.syn.get(manifest_id).path
                    manifest = pd.read_csv(manifest_filepath).fillna("")

                    print(manifest.columns)
                    if "Filename" in manifest.columns and "entityId" in manifest.columns:
                        manifest["downloadLink"] = manifest[["entityId"]].apply(lambda x: "https://www.synapse.org/#!Synapse:" + x["entityId"], axis = 1)

                    if not data_type in data_preview:
                        data_preview_update = {
                                    data_type:{
                                        component:{
                                                    "dataLink":data_link,
                                                    "data":{
                                                            "attributes":[],
                                                            "values":[],
                                                            "manifest_link": manifest_link
                                                    }
                                        }
                                    }
                        }

                        data_preview[project_name].update(data_preview_update)

                    # if dataType is assay the manifest should contain column downloadLink, containing links to dataset files on Synapse
                    # if component is scRNA-seq level 3/4 the manifest should contain column view, containing cBioPortal links
                    # if data type is imaging the manifest should contain column view, containing imaging links

            
                    #get data attributes
                    for attr in manifest.columns:
                        
                        description = sg.get_node_definition(se, attr)
                        if attr == "downloadLink":
                            description = "Download file from Synapse"

                        # for now this is empty;
                        # in the future we might inject SEO or other metadata
                        schema_meta = ""


                        attribute = {
                                "name":attr,
                                "description":description,
                                "schemaMetadata":schema_meta
                        }

                        data_preview[project_name][data_type][component]["data"]["attributes"].append(attribute)

                    data_preview[project_name][data_type][component]["data"]["values"] = manifest.values.tolist()
            

            if not data_preview[project_name]:
                del(data_preview[project_name])

        with open("./data/data_preview.json", "w") as js_f:
            json.dump(data_preview, js_f, indent = 3)

        return data_preview
